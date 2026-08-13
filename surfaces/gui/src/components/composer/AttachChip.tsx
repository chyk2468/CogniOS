import type { Attachment } from "../../types";
import { Icon } from "../Icon";

export function AttachChip({ a, onRemove }: { a: Attachment; onRemove: () => void }) {
  return (
    <div className={"attach-chip" + (a.kind === "image" ? " img" : "")}>
      {a.kind === "image" ? (
        <img src={a.data_url} alt={a.name} />
      ) : (
        <>
          <Icon name="file" size={13} />
          <span className="attach-name">{a.name}</span>
        </>
      )}
      <button className="attach-x" onClick={onRemove} title="Remove">
        ✕
      </button>
    </div>
  );
}
