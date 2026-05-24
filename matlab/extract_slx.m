function extract_slx(slxPath, outJsonPath, varargin)
%EXTRACT_SLX  Parse a Simulink .slx into canonical JSON.
%
%   extract_slx(slxPath, outJsonPath)
%   extract_slx(..., 'IncludeLibraryLinks', false)
%
%   Walks all subsystems recursively (depth-first), captures blocks, ports,
%   and parameters, and writes a deterministic JSON file matching the
%   `CanonicalModel` Pydantic schema in src/doc_agent/extract/schema.py.
%
%   Stable ids are SHA-1(first 10 hex chars) over (kind, full path).
%   Re-running on an unchanged model produces a byte-identical JSON file.

p = inputParser;
addRequired(p, 'slxPath', @(x) ischar(x) || isstring(x));
addRequired(p, 'outJsonPath', @(x) ischar(x) || isstring(x));
addParameter(p, 'IncludeLibraryLinks', false, @islogical);
parse(p, slxPath, outJsonPath, varargin{:});
opts = p.Results;

slxPath     = char(opts.slxPath);
outJsonPath = char(opts.outJsonPath);
[slxFolder, modelName, ~] = fileparts(slxPath);

% Make the model's folder visible so Simulink can resolve a linked .sldd
% by basename. (Without this we get: "Unable to find data dictionary X.sldd".)
if ~isempty(slxFolder)
    addpath(slxFolder);
end

% Load model headlessly
prevWarn = warning('off', 'Simulink:Commands:FindSystemOptionsChanged');
cleanupWarn = onCleanup(@() warning(prevWarn));
load_system(slxPath);
cleanupModel = onCleanup(@() safeClose(modelName));

% --- Header ----------------------------------------------------------
data = struct();
data.schema_version    = 1;
data.model.name        = modelName;
data.model.file        = slxPath;
data.model.version     = safeVer();
data.model.extracted_at = datestr(now, 'yyyy-mm-ddTHH:MM:SS');
data.model.extractor_version = '0.1';

% --- Subsystems (recursive flatten) ----------------------------------
data.subsystems = walkSubsystems(modelName, modelName, 0, '', opts);

% --- Top-level signal connectivity -----------------------------------
data.signals = walkLines(modelName);

% --- Stateflow walker ------------------------------------------------
data.stateflow = walkStateflow(modelName);

% --- Data dictionary — call extract_sldd.m for any linked .sldd ------
ddName = '';
try
    ddName = get_param(modelName, 'DataDictionary');
catch
end
if isempty(ddName)
    data.data_dictionary = [];   % serialized as null
else
    % Resolve to a full path. Simulink stores just the basename when the
    % dictionary is on the path; we need an absolute path for extract_sldd.
    ddFull = '';
    cand1 = which(ddName);
    if ~isempty(cand1) && isfile(cand1)
        ddFull = cand1;
    elseif isfile(fullfile(slxFolder, ddName))
        ddFull = fullfile(slxFolder, ddName);
    end

    if isempty(ddFull)
        % Couldn't locate the .sldd — keep the reference only.
        data.data_dictionary = struct( ...
            'name', ddName, 'path', ddName, ...
            'calibrations', {{}}, 'signals', {{}});
    else
        try
            data.data_dictionary = extract_sldd(ddFull);
        catch ME
            warning('extract_slx:DDFailed', ...
                    'extract_sldd failed for %s: %s', ddName, ME.message);
            data.data_dictionary = struct( ...
                'name', ddName, 'path', ddFull, ...
                'calibrations', {{}}, 'signals', {{}});
        end
    end
end

% --- Serialize -------------------------------------------------------
% MATLAB's jsonencode serializes single-element struct arrays as JSON
% objects (not 1-element arrays). Pre-process `data` so every field that
% should be a JSON list is a cell array of structs, which always rounds
% trips as `[ ... ]`.
nSubs   = numel(data.subsystems);
nLines  = numel(data.signals);
data    = prepareForJson(data);
jsonText = jsonencode(data, 'PrettyPrint', true);
fid = fopen(outJsonPath, 'w');
if fid < 0
    error('extract_slx:WriteFailed', 'Could not open %s for writing.', outJsonPath);
end
fwrite(fid, jsonText);
fclose(fid);
fprintf('extract_slx: wrote %s (%d subsystems, %d signals)\n', ...
        outJsonPath, nSubs, nLines);
end


% =====================================================================
% Recursive walker. Returns a *flat* struct array — every subsystem at
% any depth, with `path` and `parent_path` recording hierarchy.
%
% NB: every struct array in this file is pre-allocated with its full
% schema via `struct('field', {}, ...)`. MATLAB requires identical field
% sets/order when concatenating; building structs ad hoc and appending
% with `arr(end+1) = s` is fragile.
% =====================================================================
function out = walkSubsystems(rootPath, currentPath, depth, parentPath, opts)
out = struct( ...
    'id', {}, 'name', {}, 'path', {}, 'depth', {}, 'parent_path', {}, ...
    'is_atomic', {}, 'is_virtual', {}, 'inports', {}, 'outports', {}, ...
    'blocks', {}, 'child_subsystem_paths', {}, 'annotations', {}, ...
    'provenance', {});

children = find_system(currentPath, 'SearchDepth', 1, 'BlockType', 'SubSystem');
children = children(~strcmp(children, currentPath));

if ~opts.IncludeLibraryLinks
    keep = true(size(children));
    for i = 1:numel(children)
        try
            if ~strcmpi(get_param(children{i}, 'LinkStatus'), 'none')
                keep(i) = false;
            end
        catch
        end
    end
    children = children(keep);
end

for i = 1:numel(children)
    ssPath = children{i};

    % Immediate child-subsystems of *this* subsystem (one level deeper)
    direct = find_system(ssPath, 'SearchDepth', 1, 'BlockType', 'SubSystem');
    direct = direct(~strcmp(direct, ssPath));

    n = numel(out) + 1;
    out(n).id          = stableId('subsystem', ssPath);
    out(n).name        = char(get_param(ssPath, 'Name'));
    out(n).path        = ssPath;
    out(n).depth       = depth + 1;
    out(n).parent_path = currentPath;
    out(n).is_atomic   = strcmpi(safeGet(ssPath, 'TreatAsAtomicUnit', 'off'), 'on');
    out(n).is_virtual  = ~out(n).is_atomic;
    out(n).inports     = capturePorts(ssPath, 'Inport');
    out(n).outports    = capturePorts(ssPath, 'Outport');
    out(n).blocks      = captureBlocks(ssPath);
    out(n).child_subsystem_paths = direct;
    out(n).annotations = captureAnnotations(ssPath);
    out(n).provenance  = struct('source', rootPath, 'element', ssPath, 'version', '');

    nested = walkSubsystems(rootPath, ssPath, depth + 1, currentPath, opts);
    if ~isempty(nested)
        out = [out, nested];   %#ok<AGROW>
    end
end
end


% =====================================================================
% Port capture — inports / outports of a subsystem (depth 1 only).
% =====================================================================
function ports = capturePorts(ssPath, blockType)
ports = struct('name', {}, 'port_number', {}, 'data_type', {}, ...
               'dimensions', {}, 'sample_time', {});
blocks = find_system(ssPath, 'SearchDepth', 1, 'BlockType', blockType);
for i = 1:numel(blocks)
    b = blocks{i};
    n = numel(ports) + 1;
    ports(n).name        = char(get_param(b, 'Name'));
    ports(n).port_number = str2doubleSafe(safeGet(b, 'Port', num2str(i)));
    ports(n).data_type   = safeGet(b, 'OutDataTypeStr', '');
    ports(n).dimensions  = safeGet(b, 'PortDimensions', '');
    ports(n).sample_time = safeGet(b, 'SampleTime', '');
end
if ~isempty(ports)
    [~, order] = sort([ports.port_number]);
    ports = ports(order);
end
end


% =====================================================================
% Leaf (non-subsystem, non-port) blocks at depth 1 inside ssPath.
% =====================================================================
function blocks = captureBlocks(ssPath)
blocks = struct('id', {}, 'name', {}, 'type', {}, 'parameters', {}, ...
                'referenced_calibrations', {}, 'link_status', {}, 'provenance', {});
all = find_system(ssPath, 'SearchDepth', 1, 'Type', 'block');
for i = 1:numel(all)
    b = all{i};
    if strcmp(b, ssPath); continue; end
    bt = '';
    try
        bt = char(get_param(b, 'BlockType'));
    catch
        continue;
    end
    if any(strcmp(bt, {'SubSystem', 'Inport', 'Outport'}))
        continue;
    end
    n = numel(blocks) + 1;
    blocks(n).id                       = stableId('block', b);
    blocks(n).name                     = char(get_param(b, 'Name'));
    blocks(n).type                     = bt;
    blocks(n).parameters               = captureParameters(b, bt);
    blocks(n).referenced_calibrations  = findCalibRefs(blocks(n).parameters);
    blocks(n).link_status              = safeGet(b, 'LinkStatus', 'none');
    blocks(n).provenance               = struct('source', bdroot(b), 'element', b, 'version', '');
end
end


% =====================================================================
% Per-block-type parameter capture (extensible — add more as needed).
% =====================================================================
function params = captureParameters(blk, blkType)
params = struct();
keys = paramsForType(blkType);
for i = 1:numel(keys)
    k = keys{i};
    v = safeGet(blk, k, '');
    if ~isempty(v)
        % Ensure field name is valid; replace dots, spaces
        validKey = matlab.lang.makeValidName(k);
        params.(validKey) = v;
    end
end
end


function ks = paramsForType(blkType)
switch blkType
    case 'Gain';            ks = {'Gain', 'Multiplication', 'OutDataTypeStr'};
    case 'Sum';             ks = {'Inputs', 'IconShape', 'OutDataTypeStr'};
    case 'TransferFcn';     ks = {'Numerator', 'Denominator', 'AbsoluteTolerance'};
    case 'Constant';        ks = {'Value', 'OutDataTypeStr', 'SampleTime'};
    case 'Saturate';        ks = {'UpperLimit', 'LowerLimit'};
    case 'Switch';          ks = {'Criteria', 'Threshold'};
    case 'DiscreteFilter';  ks = {'Numerator', 'Denominator', 'SampleTime'};
    case 'Product';         ks = {'Inputs', 'Multiplication'};
    case 'UnitDelay';       ks = {'X0', 'SampleTime'};
    case 'Integrator';      ks = {'InitialCondition', 'UpperSaturationLimit', 'LowerSaturationLimit'};
    otherwise;              ks = {};
end
end


% =====================================================================
% Heuristic: ALL_CAPS_WITH_UNDERSCORES tokens in any parameter are
% candidate calibration references.
% =====================================================================
function refs = findCalibRefs(paramsStruct)
refs = {};
flds = fieldnames(paramsStruct);
for i = 1:numel(flds)
    v = paramsStruct.(flds{i});
    if ~ischar(v); continue; end
    matches = regexp(v, '\<[A-Z][A-Z0-9_]*[A-Z0-9]\>', 'match');
    for m = 1:numel(matches)
        tok = matches{m};
        if contains(tok, '_') && ~ismember(tok, refs)
            refs{end+1} = tok;   %#ok<AGROW>
        end
    end
end
end


% =====================================================================
function anns = captureAnnotations(ssPath)
anns = {};
ann = find_system(ssPath, 'SearchDepth', 1, 'FindAll', 'on', 'Type', 'annotation');
for i = 1:numel(ann)
    try
        txt = char(get_param(ann(i), 'Text'));
        if ~isempty(strtrim(txt))
            anns{end+1} = txt;   %#ok<AGROW>
        end
    catch
    end
end
end


% =====================================================================
% Stateflow charts in this model. Returns a flat list of chart structs.
% If Stateflow isn't installed, or the model has no charts, returns [].
% =====================================================================
function out = walkStateflow(modelName)
out = struct('id', {}, 'name', {}, 'path', {}, 'states', {}, ...
             'transitions', {}, 'provenance', {});

% sfroot is provided by Stateflow — silently bail if not installed
try
    root = sfroot();
catch
    return;
end

try
    charts = root.find('-isa', 'Stateflow.Chart');
catch
    return;
end

mPath = bdroot(modelName);
for i = 1:numel(charts)
    c = charts(i);
    chartPath = '';
    try
        chartPath = char(c.Path);
    catch
    end
    if isempty(chartPath); continue; end
    % Only charts belonging to *our* model
    if ~startsWith(chartPath, mPath); continue; end

    n = numel(out) + 1;
    out(n).id          = stableId('stateflow', chartPath);
    try; out(n).name = char(c.Name); catch; out(n).name = ''; end
    out(n).path        = chartPath;
    out(n).states      = walkStates(c);
    out(n).transitions = walkTransitions(c);
    out(n).provenance  = struct('source', modelName, 'element', chartPath, 'version', '');
end
end


function s_arr = walkStates(chart)
s_arr = struct('id', {}, 'name', {}, 'is_atomic', {}, 'actions', {});
try
    states = chart.find('-isa', 'Stateflow.State');
catch
    return;
end
for i = 1:numel(states)
    st = states(i);
    try; nm = char(st.Name); catch; nm = ''; end
    try; pth = char(st.Path); catch; pth = nm; end
    n = numel(s_arr) + 1;
    s_arr(n).id        = stableId('sfstate', pth);
    s_arr(n).name      = nm;
    s_arr(n).is_atomic = strcmpi(sfSafeProp(st, 'IsSubchart', 'off'), 'off');  % atomic = not a subchart container
    actions = struct( ...
        'entry',  char(sfSafeProp(st, 'EntryAction',  '')), ...
        'during', char(sfSafeProp(st, 'DuringAction', '')), ...
        'exit',   char(sfSafeProp(st, 'ExitAction',   '')) ...
    );
    s_arr(n).actions = actions;
end
end


function t_arr = walkTransitions(chart)
t_arr = struct('id', {}, 'source', {}, 'destination', {}, ...
               'condition', {}, 'action', {});
try
    trans = chart.find('-isa', 'Stateflow.Transition');
catch
    return;
end
for i = 1:numel(trans)
    t = trans(i);
    srcName = '';
    dstName = '';
    try
        if ~isempty(t.Source); srcName = char(t.Source.Name); end
    catch
    end
    try
        if ~isempty(t.Destination); dstName = char(t.Destination.Name); end
    catch
    end
    n = numel(t_arr) + 1;
    keyStr = sprintf('%s::%s->%s::%d', char(chart.Path), srcName, dstName, i);
    t_arr(n).id          = stableId('sftrans', keyStr);
    t_arr(n).source      = srcName;
    t_arr(n).destination = dstName;
    t_arr(n).condition   = char(sfSafeProp(t, 'Condition', ''));
    t_arr(n).action      = char(sfSafeProp(t, 'ConditionAction', ''));
end
end


function v = sfSafeProp(obj, name, default)
% Like safeGet but for Stateflow API objects (no get_param).
try
    raw = obj.(name);
    if isnumeric(raw); v = mat2str(raw);
    elseif islogical(raw); v = sprintf('%d', raw);
    else; v = char(string(raw));
    end
catch
    v = default;
end
end


% =====================================================================
% Top-level signal lines.
% =====================================================================
function out = walkLines(modelName)
out = struct('id', {}, 'name', {}, 'from_block', {}, 'to_block', {}, 'provenance', {});
lines = find_system(modelName, 'SearchDepth', 1, 'FindAll', 'on', 'Type', 'line');
for i = 1:numel(lines)
    L = lines(i);
    name = char(get_param(L, 'Name'));
    src  = get_param(L, 'SrcBlockHandle');
    dst  = get_param(L, 'DstBlockHandle');
    fromName = safeBlockPath(src);
    toName   = safeBlockPath(dst);
    if isempty(fromName) && isempty(toName); continue; end
    n = numel(out) + 1;
    out(n).id          = stableId('signal', sprintf('%s::%s->%s', modelName, fromName, toName));
    out(n).name        = name;
    out(n).from_block  = fromName;
    out(n).to_block    = toName;
    out(n).provenance  = struct('source', modelName, ...
                                 'element', sprintf('line:%s->%s', fromName, toName), ...
                                 'version', '');
end
end


% =====================================================================
% Helpers
% =====================================================================
function id = stableId(kind, key)
% Deterministic 10-hex-char id from SHA-1((kind, key)). Java is bundled
% with MATLAB so this is always available, no toolbox required.
import java.security.MessageDigest
md = MessageDigest.getInstance('SHA-1');
md.update(unicode2native(sprintf('%s::%s', char(kind), char(key)), 'UTF-8'));
bytes = typecast(md.digest(), 'uint8');
hex = lower(reshape(dec2hex(bytes, 2)', 1, []));
id = hex(1:10);
end

function v = safeGet(blk, name, default)
try
    raw = get_param(blk, name);
    if isnumeric(raw)
        v = mat2str(raw);
    elseif islogical(raw)
        v = sprintf('%d', raw);
    else
        v = char(string(raw));
    end
catch
    v = default;
end
end

function v = safeVer()
try
    v = char(version('-release'));
catch
    v = '';
end
end

function p = safeBlockPath(h)
try
    p = char(getfullname(h));
catch
    p = '';
end
end

function n = str2doubleSafe(s)
n = str2double(s);
if isnan(n); n = 1; end
end

function safeClose(modelName)
try
    if bdIsLoaded(modelName)
        close_system(modelName, 0);
    end
catch
end
end


% =====================================================================
% prepareForJson — make MATLAB's jsonencode behave for list-typed fields.
%
% Problem: jsonencode() of a 1-element struct array drops the array
% wrapper and emits a JSON object. Same input as a 2-element struct array
% emits a JSON array. Pydantic (rightly) refuses the inconsistency.
%
% Solution: recursively convert every struct array to a cell array of
% scalar structs. Cell arrays always serialize as JSON arrays,
% regardless of length (0, 1, or N).
%
% For SCALAR struct fields whose *name* says "this is a list", we wrap
% the lone struct in a 1-cell so it still becomes a 1-element JSON array.
% =====================================================================
function out = prepareForJson(in, listFields)
if nargin < 2
    listFields = { ...
        'subsystems', 'signals', 'stateflow', ...
        'inports', 'outports', 'blocks', ...
        'child_subsystem_paths', 'annotations', 'referenced_calibrations', ...
        'calibrations', ...
        'states', 'transitions' ...
    };
end

if isstruct(in) && ~isscalar(in)
    % Empty or multi-element struct array → cell array of scalar structs
    out = cell(1, numel(in));
    for i = 1:numel(in)
        out{i} = prepareForJson(in(i), listFields);
    end
elseif isstruct(in)
    % Scalar struct — recurse into fields, applying the list-name rule
    out = struct();
    flds = fieldnames(in);
    for i = 1:numel(flds)
        f = flds{i};
        recursed = prepareForJson(in.(f), listFields);
        % If this field name is "supposed to be a list" and the recursed
        % value is still a scalar struct, wrap it so it serializes as
        % a 1-element JSON array.
        if ismember(f, listFields) && isstruct(recursed) && isscalar(recursed)
            out.(f) = {recursed};
        else
            out.(f) = recursed;
        end
    end
elseif iscell(in)
    out = cell(size(in));
    for i = 1:numel(in)
        out{i} = prepareForJson(in{i}, listFields);
    end
else
    out = in;
end
end
