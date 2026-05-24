function build_test_model(outDir)
%BUILD_TEST_MODEL  Programmatically build VSEModel.slx + VSEModel.sldd.
%
%   build_test_model()          % writes to current folder
%   build_test_model('path')    % writes to a specific folder
%
%   This produces a small but real Simulink model + data dictionary so
%   `extract_slx.m` has something to chew on. The model implements a toy
%   Vehicle Speed Estimator (VSE):
%
%       vWheelFL_rps ─┐
%                     ├─► WheelAverager ─► LowPassFilter ─► UnitConverter ─► vEgo_kmh
%       vWheelFR_rps ─┘
%
%   Calibrations defined in the .sldd:
%       K_VSE_FILT_TC          (s)     low-pass time constant
%       K_TIRE_ROLLING_RADIUS  (m)     effective rolling radius
%       K_VSE_MIN_SPEED        (km/h)  output floor
%       K_VSE_MAX_SPEED        (km/h)  output ceiling
%
%   The script is idempotent — re-running deletes the old files first.

    if nargin < 1 || isempty(outDir)
        outDir = pwd;
    end
    outDir = char(outDir);
    if ~isfolder(outDir)
        mkdir(outDir);
    end

    modelName = 'VSEModel';
    slxPath   = fullfile(outDir, [modelName, '.slx']);
    ddPath    = fullfile(outDir, [modelName, '.sldd']);

    % ------ 1. Data dictionary -----------------------------------------
    if exist(ddPath, 'file')
        delete(ddPath);
    end
    dd = Simulink.data.dictionary.create(ddPath);
    ds = getSection(dd, 'Design Data');

    cals = {
        'K_VSE_FILT_TC',          0.05,   's',     0.01, 1.0,   'Low-pass filter time constant';
        'K_TIRE_ROLLING_RADIUS',  0.3,    'm',     0.2,  0.5,   'Effective tire rolling radius';
        'K_VSE_MIN_SPEED',        0.0,    'km/h',  0.0,  5.0,   'Output floor';
        'K_VSE_MAX_SPEED',        300.0,  'km/h',  100,  400,   'Output ceiling';
    };
    for i = 1:size(cals, 1)
        p             = Simulink.Parameter;
        p.Value       = cals{i, 2};
        p.DataType    = 'double';
        p.Min         = cals{i, 4};
        p.Max         = cals{i, 5};
        p.Description = cals{i, 6};
        addEntry(ds, cals{i, 1}, p);
    end

    % A non-calibration signal entry as well
    sig             = Simulink.Signal;
    sig.DataType    = 'double';
    sig.Description = 'Filtered ego-vehicle speed (output of the VSE).';
    addEntry(ds, 'vEgo_kmh', sig);

    saveChanges(dd);
    close(dd);

    % ------ 2. Build the model -----------------------------------------
    if bdIsLoaded(modelName)
        close_system(modelName, 0);
    end
    if exist(slxPath, 'file')
        delete(slxPath);
    end

    new_system(modelName);
    open_system(modelName);

    % Make sure Simulink can resolve VSEModel.sldd by name.
    % (Simulink searches MATLAB path; outDir might not be on it yet.)
    addpath(outDir);
    set_param(modelName, 'DataDictionary', [modelName, '.sldd']);

    % Top-level inports
    add_block('simulink/Sources/In1', sprintf('%s/vWheelFL_rps', modelName), ...
              'Position', [40 60 70 80]);
    add_block('simulink/Sources/In1', sprintf('%s/vWheelFR_rps', modelName), ...
              'Position', [40 130 70 150], 'Port', '2');

    % ---- Subsystem 1: WheelAverager (avg of two wheel speeds) ---------
    ssA = sprintf('%s/WheelAverager', modelName);
    add_block('simulink/Ports & Subsystems/Subsystem', ssA, 'Position', [150 70 270 150]);
    Simulink.SubSystem.deleteContents(ssA);
    add_block('simulink/Ports & Subsystems/In1',  sprintf('%s/In1', ssA),  'Position', [40 40 60 60]);
    add_block('simulink/Ports & Subsystems/In1',  sprintf('%s/In2', ssA),  'Position', [40 110 60 130], 'Port', '2');
    add_block('simulink/Math Operations/Sum',     sprintf('%s/Sum', ssA),  'Position', [130 60 160 110], 'Inputs', '++');
    add_block('simulink/Math Operations/Gain',    sprintf('%s/Half', ssA), 'Position', [200 70 240 100], 'Gain', '0.5');
    add_block('simulink/Ports & Subsystems/Out1', sprintf('%s/Out1', ssA), 'Position', [280 75 300 95]);
    add_line(ssA, 'In1/1',  'Sum/1');
    add_line(ssA, 'In2/1',  'Sum/2');
    add_line(ssA, 'Sum/1',  'Half/1');
    add_line(ssA, 'Half/1', 'Out1/1');

    % ---- Subsystem 2: LowPassFilter (uses K_VSE_FILT_TC) --------------
    % NB: a Gain block stands in for a real LPF — this fixture only needs to be
    % structurally valid; we never simulate it, we only let extract_slx.m walk it.
    ssB = sprintf('%s/LowPassFilter', modelName);
    add_block('simulink/Ports & Subsystems/Subsystem', ssB, 'Position', [330 80 460 140]);
    Simulink.SubSystem.deleteContents(ssB);
    add_block('simulink/Ports & Subsystems/In1',  sprintf('%s/In1', ssB),         'Position', [40 70 60 90]);
    add_block('simulink/Math Operations/Gain',    sprintf('%s/FilterGain', ssB),  'Position', [120 60 220 110], ...
              'Gain', 'K_VSE_FILT_TC');
    add_block('simulink/Ports & Subsystems/Out1', sprintf('%s/Out1', ssB),        'Position', [260 75 280 95]);
    add_line(ssB, 'In1/1',        'FilterGain/1');
    add_line(ssB, 'FilterGain/1', 'Out1/1');

    % ---- Subsystem 3: UnitConverter (rolling radius + m/s→km/h + clamp) -------
    ssC = sprintf('%s/UnitConverter', modelName);
    add_block('simulink/Ports & Subsystems/Subsystem', ssC, 'Position', [520 80 660 140]);
    Simulink.SubSystem.deleteContents(ssC);
    add_block('simulink/Ports & Subsystems/In1',  sprintf('%s/In1', ssC),         'Position', [40 70 60 90]);
    add_block('simulink/Math Operations/Gain',    sprintf('%s/RadiusToLin', ssC), 'Position', [110 60 190 110], ...
              'Gain', 'K_TIRE_ROLLING_RADIUS');
    add_block('simulink/Math Operations/Gain',    sprintf('%s/MsToKmh', ssC),     'Position', [230 60 310 110], ...
              'Gain', '3.6');
    add_block('simulink/Math Operations/Gain',    sprintf('%s/ClampGain', ssC),   'Position', [340 60 420 110], ...
              'Gain', 'K_VSE_MAX_SPEED / 300');
    add_block('simulink/Ports & Subsystems/Out1', sprintf('%s/Out1', ssC),        'Position', [450 75 470 95]);
    add_line(ssC, 'In1/1',         'RadiusToLin/1');
    add_line(ssC, 'RadiusToLin/1', 'MsToKmh/1');
    add_line(ssC, 'MsToKmh/1',     'ClampGain/1');
    add_line(ssC, 'ClampGain/1',   'Out1/1');

    % Top-level outport
    add_block('simulink/Sinks/Out1', sprintf('%s/vEgo_kmh', modelName), ...
              'Position', [720 95 750 115]);

    % Top-level wiring
    add_line(modelName, 'vWheelFL_rps/1', 'WheelAverager/1', 'autorouting', 'on');
    add_line(modelName, 'vWheelFR_rps/1', 'WheelAverager/2', 'autorouting', 'on');
    add_line(modelName, 'WheelAverager/1', 'LowPassFilter/1', 'autorouting', 'on');
    add_line(modelName, 'LowPassFilter/1', 'UnitConverter/1', 'autorouting', 'on');
    add_line(modelName, 'UnitConverter/1', 'vEgo_kmh/1', 'autorouting', 'on');

    % An annotation so we get one in the canonical JSON
    add_block('built-in/Note', sprintf('%s/note', modelName), ...
              'Position', [40 220 600 240], ...
              'Text', 'Toy VSE model — generated by build_test_model.m');

    % ------ 3. Save + close --------------------------------------------
    save_system(modelName, slxPath);
    close_system(modelName, 0);

    fprintf('Wrote %s\n', slxPath);
    fprintf('Wrote %s\n', ddPath);
end
