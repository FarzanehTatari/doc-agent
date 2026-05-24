function dd_data = extract_sldd(ddPath)
%EXTRACT_SLDD  Walk a Simulink Data Dictionary (.sldd) and return its contents.
%
%   dd_data = extract_sldd(ddPath)
%
%   Returns a struct shaped to match the `DataDictionary` Pydantic model in
%   src/doc_agent/extract/schema.py:
%
%       dd_data.name           — basename
%       dd_data.path           — absolute path
%       dd_data.calibrations   — cell array of calibration structs (Simulink.Parameter)
%       dd_data.signals        — cell array of signal structs (Simulink.Signal)
%
%   Units are parsed from a trailing `[unit]` token in the Description field
%   (the convention `build_test_model.m` uses). If there's no such token,
%   `units` is left empty.
%
%   This script is intentionally standalone — extract_slx.m calls it for any
%   linked dictionary, but you can also run it directly:
%       d = extract_sldd('/path/to/MyDict.sldd');

if nargin < 1 || isempty(ddPath)
    error('extract_sldd:NoPath', 'A path to a .sldd file is required.');
end
ddPath = char(ddPath);
if ~isfile(ddPath)
    error('extract_sldd:NotFound', 'No such file: %s', ddPath);
end

[~, baseName, ~] = fileparts(ddPath);

dd_data = struct( ...
    'name',         [baseName, '.sldd'], ...
    'path',         ddPath, ...
    'calibrations', {{}}, ...
    'signals',      {{}});

dd = Simulink.data.dictionary.open(ddPath);
cleanup = onCleanup(@() close(dd));

% --- Design Data section is where Parameters / Signals live ---------------
try
    ds = getSection(dd, 'Design Data');
catch
    % No Design Data section — nothing to walk; return the empty stub.
    return;
end

entries = find(ds);
for i = 1:length(entries)
    e = entries(i);
    entryName = char(e.Name);
    try
        val = getValue(e);
    catch
        continue;
    end
    cls = class(val);

    switch cls
        case 'Simulink.Parameter'
            dd_data.calibrations{end+1} = capParameter(entryName, val, ddPath);   %#ok<AGROW>
        case 'Simulink.Signal'
            dd_data.signals{end+1} = capSignal(entryName, val, ddPath);   %#ok<AGROW>
        otherwise
            % Skip Bus, Enum, alias types for now — Slice 3 territory.
    end
end
end


% =====================================================================
function out = capParameter(name, p, ddPath)
out = struct();
out.id          = sllStableId('calibration', sprintf('%s::%s', ddPath, name));
out.name        = name;
out.value       = numericToString(safeProp(p, 'Value', ''));
out.data_type   = safeProp(p, 'DataType', '');
out.units       = parseUnits(safeProp(p, 'Description', ''));
out.min         = numericToString(safeProp(p, 'Min', ''));
out.max         = numericToString(safeProp(p, 'Max', ''));
out.description = stripUnits(safeProp(p, 'Description', ''));
out.provenance  = struct('source', ddPath, 'element', name, 'version', '');
end


function out = capSignal(name, s, ddPath)
out = struct();
out.id          = sllStableId('dd_signal', sprintf('%s::%s', ddPath, name));
out.name        = name;
out.data_type   = safeProp(s, 'DataType', '');
out.dimensions  = numericToString(safeProp(s, 'Dimensions', ''));
out.description = stripUnits(safeProp(s, 'Description', ''));
out.provenance  = struct('source', ddPath, 'element', name, 'version', '');
end


% =====================================================================
% Helpers — duplicated from extract_slx.m so this script stands alone.
% =====================================================================
function id = sllStableId(kind, key)
import java.security.MessageDigest
md = MessageDigest.getInstance('SHA-1');
md.update(unicode2native(sprintf('%s::%s', char(kind), char(key)), 'UTF-8'));
bytes = typecast(md.digest(), 'uint8');
hex = lower(reshape(dec2hex(bytes, 2)', 1, []));
id = hex(1:10);
end


function v = safeProp(obj, name, default)
try
    raw = obj.(name);
    if isnumeric(raw)
        v = raw;          % return numeric — caller stringifies
    elseif islogical(raw)
        v = raw;
    else
        v = char(string(raw));
    end
catch
    v = default;
end
end


function s = numericToString(v)
% Convert MATLAB value to its canonical string form. Empty / missing → ''.
if isempty(v)
    s = '';
elseif isnumeric(v)
    s = mat2str(v);
elseif islogical(v)
    s = sprintf('%d', v);
elseif ischar(v) || isstring(v)
    s = char(v);
else
    s = '';
end
end


function u = parseUnits(desc)
% Pull "[unit]" trailing token out of a Description string.
m = regexp(char(desc), '\[([^\[\]]+)\]\s*$', 'tokens', 'once');
if isempty(m)
    u = '';
else
    u = strtrim(m{1});
end
end


function d = stripUnits(desc)
% Remove a trailing "[unit]" token from a Description, return the prose only.
d = regexprep(char(desc), '\s*\[[^\[\]]+\]\s*$', '');
d = strtrim(d);
end
