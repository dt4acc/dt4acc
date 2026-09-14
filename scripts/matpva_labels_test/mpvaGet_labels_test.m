%% Test script: verify ORBITCC:rdBpm / ORBITCC:rdModel are readable via matpva
%
% Confirms the fix in orbit_pva.py (added the "labels" field the NTTable
% normative type requires) actually resolves the "field labels is
% missing" error reported against matpva's mpvaGet.
%
% Prerequisites:
%   - matpva installed and on the MATLAB path
%     (https://github.com/slaclab/matpva)
%   - Python 3.8.13+ with p4p 3.5.5+ available to MATLAB
%     (matpva's own prerequisites — see its README.md)
%   - scripts/matpva_labels_test/run_orbit_pv_server.py running
%     (same host, or PVAccess discovery configured across hosts)
%
% Usage:
%   1. In a terminal: python3 scripts/matpva_labels_test/run_orbit_pv_server.py
%   2. In MATLAB, with matpva on the path:
%        run("scripts/matpva_labels_test/mpvaGet_labels_test.m")

pv_names = ["ORBITCC:rdBpm", "ORBITCC:rdModel"];

expected_columns = { ...
    ["BPM", "X", "Y", "A", "B", "C", "D"], ...
    ["BPM", "SPos", "BetaHor", "BetaVer", "PhaseAdvanceHor", "PhaseAdvanceVer"] ...
};

all_passed = true;

for i = 1:numel(pv_names)
    pv_name = pv_names(i);
    fprintf("\n--- %s ---\n", pv_name);

    try
        [NTTable, ts, alarm, NTStruct] = mpvaGet(pv_name); %#ok<ASGLU>
    catch err
        fprintf("FAIL: mpvaGet(%s) raised an error:\n  %s\n", pv_name, err.message);
        all_passed = false;
        continue
    end

    disp(NTTable);

    got_columns = string(NTTable.Properties.VariableNames);
    want_columns = expected_columns{i};

    if isequal(got_columns, want_columns)
        fprintf("PASS: %s columns match expected labels %s\n", ...
            pv_name, strjoin(want_columns, ", "));
    else
        fprintf("FAIL: %s columns %s do not match expected %s\n", ...
            pv_name, strjoin(got_columns, ", "), strjoin(want_columns, ", "));
        all_passed = false;
    end
end

fprintf("\n============================\n");
if all_passed
    fprintf("ALL PASSED — labels fix confirmed against matpva.\n");
else
    fprintf("SOME CHECKS FAILED — see above.\n");
end
