import { useEffect, useState } from "react";
import {
  applyMappingProfile,
  createMappingProfile,
  deleteMappingProfile,
  fetchSourceFields,
  fetchTargetFields,
  listMappingProfiles,
  type ApplyMappingResult,
  type FieldMapping,
  type LineSubfieldDef,
  type MappingProfile,
  type SourceField,
  type TargetFieldDef,
} from "../api";

function encodeKey(sf: SourceField): string {
  return `${sf.segmentIndex}.${sf.elementIndex}.${sf.componentIndex}`;
}

function decodeKey(key: string): FieldMapping["source"] {
  const [segment_index, element_index, component_index] = key.split(".").map(Number);
  return { segment_index, element_index, component_index };
}

export function MappingTab() {
  const [sampleContent, setSampleContent] = useState("");
  const [sourceFields, setSourceFields] = useState<SourceField[]>([]);
  const [targetDefs, setTargetDefs] = useState<{
    header: TargetFieldDef[];
    lineSubfields: LineSubfieldDef[];
  } | null>(null);

  const [headerMap, setHeaderMap] = useState<Record<string, string>>({});
  const [lineGroups, setLineGroups] = useState<Record<string, string>[]>([{}]);
  const [profileName, setProfileName] = useState("");

  const [profiles, setProfiles] = useState<MappingProfile[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState<number | "">("");
  const [applyContent, setApplyContent] = useState("");
  const [applyResult, setApplyResult] = useState<ApplyMappingResult | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchTargetFields().then(setTargetDefs).catch((err) => setError(String(err)));
    refreshProfiles();
  }, []);

  async function refreshProfiles() {
    try {
      setProfiles(await listMappingProfiles());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleLoadFields() {
    if (!sampleContent.trim()) {
      setError("paste a sample EDIFACT message first");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const { fields } = await fetchSourceFields(sampleContent);
      setSourceFields(fields);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  function buildFieldMappings(): FieldMapping[] {
    const mappings: FieldMapping[] = [];
    for (const [field, key] of Object.entries(headerMap)) {
      if (key) mappings.push({ target_field: field, source: decodeKey(key) });
    }
    lineGroups.forEach((group, i) => {
      for (const [subfield, key] of Object.entries(group)) {
        if (key) mappings.push({ target_field: `line_${i}.${subfield}`, source: decodeKey(key) });
      }
    });
    return mappings;
  }

  async function handleSaveProfile() {
    if (!profileName.trim()) {
      setError("name the mapping before saving");
      return;
    }
    setLoading(true);
    setError(null);
    setSaveMessage(null);
    try {
      const created = await createMappingProfile({
        name: profileName,
        fromFormat: "edifact",
        toFormat: "ubl",
        fieldMappings: buildFieldMappings(),
      });
      setSaveMessage(`Saved "${created.name}".`);
      await refreshProfiles();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleDeleteProfile(id: number) {
    await deleteMappingProfile(id);
    if (selectedProfileId === id) setSelectedProfileId("");
    await refreshProfiles();
  }

  async function handleApply() {
    if (!selectedProfileId) {
      setError("pick a saved mapping first");
      return;
    }
    if (!applyContent.trim()) {
      setError("paste a document to apply the mapping to");
      return;
    }
    setLoading(true);
    setError(null);
    setApplyResult(null);
    try {
      setApplyResult(await applyMappingProfile(Number(selectedProfileId), applyContent));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  const sourceOptions = sourceFields.map((sf) => (
    <option key={encodeKey(sf)} value={encodeKey(sf)}>
      {sf.label}
    </option>
  ));

  return (
    <div className="panel">
      <p className="panel-description">
        Build a reusable EDIFACT → UBL field mapping from a sample message, then apply it to any
        document with the same segment shape. Positional, not AI-guessed — you pick every
        correspondence.
      </p>

      <h4>1. Load fields from a sample message</h4>
      <textarea
        className="content-input"
        placeholder="Paste a sample EDIFACT INVOIC message…"
        value={sampleContent}
        onChange={(e) => setSampleContent(e.target.value)}
        rows={6}
      />
      <div className="form-row">
        <button onClick={handleLoadFields} disabled={loading}>
          Load fields
        </button>
        {sourceFields.length > 0 && <span className="hint">{sourceFields.length} source fields found</span>}
      </div>

      {error && <div className="error-box">{error}</div>}

      {targetDefs && sourceFields.length > 0 && (
        <>
          <h4>2. Map header fields</h4>
          <table className="segments-table">
            <tbody>
              {targetDefs.header.map((t) => (
                <tr key={t.field}>
                  <td>{t.label}</td>
                  <td>
                    <select
                      value={headerMap[t.field] ?? ""}
                      onChange={(e) => setHeaderMap({ ...headerMap, [t.field]: e.target.value })}
                    >
                      <option value="">— none —</option>
                      {sourceOptions}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <h4>3. Map line items</h4>
          {lineGroups.map((group, i) => (
            <table className="segments-table" key={i}>
              <thead>
                <tr>
                  <th colSpan={2}>Line {i + 1}</th>
                </tr>
              </thead>
              <tbody>
                {targetDefs.lineSubfields.map((t) => (
                  <tr key={t.subfield}>
                    <td>{t.label}</td>
                    <td>
                      <select
                        value={group[t.subfield] ?? ""}
                        onChange={(e) => {
                          const next = [...lineGroups];
                          next[i] = { ...next[i], [t.subfield]: e.target.value };
                          setLineGroups(next);
                        }}
                      >
                        <option value="">— none —</option>
                        {sourceOptions}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ))}
          <div className="form-row">
            <button onClick={() => setLineGroups([...lineGroups, {}])}>+ Add line-item mapping</button>
          </div>

          <h4>4. Save</h4>
          <div className="form-row">
            <label>
              Mapping name
              <input
                type="text"
                placeholder="e.g. Acme supplier EDIFACT → UBL"
                value={profileName}
                onChange={(e) => setProfileName(e.target.value)}
              />
            </label>
            <button onClick={handleSaveProfile} disabled={loading}>
              Save mapping
            </button>
          </div>
          {saveMessage && <p className="hint">{saveMessage}</p>}
        </>
      )}

      <h4>Apply a saved mapping</h4>
      <div className="form-row">
        <label>
          Mapping
          <select value={selectedProfileId} onChange={(e) => setSelectedProfileId(Number(e.target.value) || "")}>
            <option value="">— select —</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        {selectedProfileId && (
          <button onClick={() => handleDeleteProfile(Number(selectedProfileId))}>Delete</button>
        )}
      </div>
      <textarea
        className="content-input"
        placeholder="Paste an EDIFACT document to convert…"
        value={applyContent}
        onChange={(e) => setApplyContent(e.target.value)}
        rows={6}
      />
      <div className="form-row">
        <button onClick={handleApply} disabled={loading}>
          Apply mapping
        </button>
      </div>

      {applyResult && (
        <div className="result-box">
          {applyResult.error && <div className="error-box">{applyResult.error}</div>}
          {applyResult.notes && applyResult.notes.length > 0 && (
            <ul className="findings-list">
              {applyResult.notes.map((n, i) => (
                <li key={i} className="finding finding-warning">
                  {n}
                </li>
              ))}
            </ul>
          )}
          {applyResult.ubl_xml && <pre className="content-block">{applyResult.ubl_xml}</pre>}
        </div>
      )}
    </div>
  );
}
