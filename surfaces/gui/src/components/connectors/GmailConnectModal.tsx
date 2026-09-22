import { useEffect, useRef, useState } from "react";
import { getConnectors, startGmailOAuth, type Connector } from "../../api";
import { ConnectorBadge } from "../../connectors/ConnectorIcon";
import { PILL_ACCENT, TAG_ACCENT } from "./ui";

interface Props {
  c: Connector;
  accountHint?: string;
  onClose: () => void;
  onConnected: () => void;
}

export function GmailConnectModal({ c, accountHint, onClose, onConnected }: Props) {
  const [fileContent, setFileContent] = useState<Record<string, unknown> | null>(null);
  const [fileName, setFileName] = useState<string>("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [waiting, setWaiting] = useState(false);
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Poll for completion when waiting for browser authorization
  useEffect(() => {
    if (!waiting) return;
    const t = setInterval(async () => {
      try {
        const list = await getConnectors();
        const gmail = list.find((x) => x.name === "gmail");
        if (gmail?.connected) {
          const accounts = (gmail.accounts || []) as Array<{ email: string; needs_reauth: boolean }>;
          if (accountHint) {
            const acc = accounts.find((a) => a.email.toLowerCase() === accountHint.toLowerCase());
            if (acc && !acc.needs_reauth) {
              onConnected();
              return;
            }
          } else if (accounts.length > 0) {
            onConnected();
            return;
          }
        }
      } catch {
        /* keep polling */
      }
    }, 2000);
    return () => clearInterval(t);
  }, [waiting, accountHint, onConnected]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setError(null);
    setValidationError(null);
    const file = e.target.files?.[0];
    if (!file) return;

    setFileName(file.name);
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        let text = (event.target?.result as string) || "";
        // Strip BOM if present
        if (text.charCodeAt(0) === 0xfeff) {
          text = text.slice(1);
        }
        const json = JSON.parse(text);
        if (typeof json !== "object" || json === null) {
          setValidationError("Invalid credentials file: root must be a JSON object.");
          setFileContent(null);
          return;
        }
        const config = json.installed || (json.credentials && json.credentials.installed) || json;
        if (!config.client_id || !config.client_secret) {
          if (json.web) {
            setValidationError("Invalid credentials file: Desktop application OAuth client ('installed') is required, not 'web'.");
          } else {
            setValidationError("Invalid Google OAuth credentials file: missing client_id or client_secret.");
          }
          setFileContent(null);
          return;
        }
        setFileContent(json);
        setValidationError(null);
      } catch (parseErr) {
        setValidationError(`Could not parse JSON: ${parseErr instanceof Error ? parseErr.message : "Invalid JSON syntax"}`);
        setFileContent(null);
      }
    };
    reader.readAsText(file);
  };

  const handleConnect = async () => {
    if (!fileContent) return;
    setError(null);
    setWaiting(true);

    try {
      const res = await startGmailOAuth(fileContent, accountHint);
      if (!res.ok) {
        const errorMsg = res.error
          ? res.status
            ? `[HTTP ${res.status}] ${res.error}`
            : res.error
          : "Failed to start Google authorization flow.";
        setError(errorMsg);
        setWaiting(false);
      } else if (res.auth_url) {
        setAuthUrl(res.auth_url);
        // Fallback popup if browser launch was delayed
        try {
          const w = window.open(res.auth_url, "_blank");
          if (!w) {
            // Popup blocked: the user can still authorize via system browser
          }
        } catch {
          /* ignore window.open issues */
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to initiate Google OAuth.");
      setWaiting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40" data-testid="gmail-connect-modal">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div
        className="absolute left-1/2 top-[14%] -translate-x-1/2 w-[480px] max-w-[calc(100vw-2rem)] bg-panel rounded-md border border-border shadow-2xl overflow-hidden"
        role="dialog"
        aria-label={accountHint ? `Reconnect ${accountHint}` : "Connect Gmail"}
      >
        <div className="flex items-center gap-3 px-5 pt-5 pb-3 border-b border-border">
          <ConnectorBadge connector={c} size={34} title="Gmail" />
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-[16px] tracking-tight">
              {accountHint ? `Reconnect ${accountHint}` : "Connect Gmail"}
            </h3>
            <p className="text-[12.5px] text-muted">Connect your Google account securely.</p>
          </div>
          <button
            className="text-faint hover:text-fg text-[18px] leading-none px-1"
            onClick={onClose}
            title="Close"
          >
            ×
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <div className="space-y-2">
            <label className="text-[12.5px] font-medium text-fg block">
              Google OAuth credentials file
            </label>
            <input
              type="file"
              accept=".json,application/json"
              ref={fileInputRef}
              onChange={handleFileChange}
              className="hidden"
              data-testid="gmail-credentials-file-input"
            />
            <div className="flex items-center gap-2.5">
              <button
                type="button"
                className="px-3 py-1.5 rounded-md border border-border bg-bg hover:bg-bg/80 text-[13px] font-medium text-fg shadow-sm transition-colors"
                onClick={() => fileInputRef.current?.click()}
                disabled={waiting}
                data-testid="choose-credentials-btn"
              >
                Choose credentials.json
              </button>
              {fileName && (
                <span className="text-[12.5px] text-muted truncate max-w-[240px]">
                  Selected: <strong className="text-fg">{fileName}</strong>
                </span>
              )}
            </div>
            {validationError && (
              <p className="text-[12px] text-danger mt-1">{validationError}</p>
            )}
          </div>

          <div className="p-3 rounded-md bg-bg border border-border space-y-1.5 text-[12px] text-muted">
            <div className="flex items-center gap-1.5 text-fg font-medium">
              <span className="text-ok">✓</span> Offline access & automatic token refresh
            </div>
            <p className="text-faint leading-relaxed">
              Google will ask you to authorize Gmail access. Access tokens refresh automatically using local encrypted storage.
            </p>
          </div>

          <button
            className={PILL_ACCENT + " w-full !py-2.5 flex items-center justify-center"}
            onClick={handleConnect}
            disabled={waiting || !fileContent}
            data-testid="connect-with-google-btn"
          >
            {waiting ? "Check your browser…" : "Connect with Google"}
          </button>

          {authUrl && waiting && (
            <div className="text-[12px] text-center text-muted">
              Didn't open?{" "}
              <a
                href={authUrl}
                target="_blank"
                rel="noreferrer"
                className="text-accent underline font-medium"
              >
                Click here to open Google sign-in
              </a>
            </div>
          )}

          {error && (
            <div
              className="text-[12.5px] text-danger text-center bg-danger/10 p-2.5 rounded border border-danger/20"
              data-testid="gmail-oauth-error"
            >
              {error}
            </div>
          )}

          <div className="pt-1 text-[11.5px] text-faint text-center space-y-1">
            <p className="flex items-center justify-center gap-1">
              <span className={TAG_ACCENT}>Secure</span>
              <span>Credentials stay strictly on this computer · No plain text tokens logged</span>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
