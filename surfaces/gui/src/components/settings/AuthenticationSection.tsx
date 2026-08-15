import { FormEvent, useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { changePassword, changeUsername, getAccount, removeAccount, signOut, totpDisable, totpSetup, totpVerifySetup, type AccountInfo } from "../../api/auth";
import { useAuth } from "../../auth/AuthContext";
import { PanelHead } from "../IntegrationsView";
import { authInputClass } from "../../auth/AuthLayout";

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="text-[14px] font-semibold text-fg mt-8 mb-3 first:mt-0">{children}</h3>;
}

function Divider() {
  return <div className="border-t border-border my-4" />;
}

function FieldRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 py-1.5 text-[13px]">
      <span className="text-muted">{label}</span>
      <span className="text-fg font-medium truncate">{value}</span>
    </div>
  );
}

function SmallButton({ children, onClick, variant = "default" }: { children: React.ReactNode; onClick: () => void; variant?: "default" | "danger" }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "text-[12px] px-2.5 py-1.5 rounded-md border shrink-0 " +
        (variant === "danger"
          ? "border-red-500/40 text-red-500 hover:bg-red-500/10"
          : "border-border text-muted hover:text-fg hover:bg-bg")
      }
    >
      {children}
    </button>
  );
}

export function AuthenticationSection() {
  const navigate = useNavigate();
  const { setUser, signOut: authSignOut, clearAccount } = useAuth();
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [sessionActivity, setSessionActivity] = useState<string>("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const [showUsername, setShowUsername] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showTotpSetup, setShowTotpSetup] = useState(false);
  const [showTotpDisable, setShowTotpDisable] = useState(false);

  const [newUsername, setNewUsername] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const [manualKey, setManualKey] = useState("");
  const [qrBase64, setQrBase64] = useState("");

  const [showRemoveDialog, setShowRemoveDialog] = useState(false);
  const [removeConfirm, setRemoveConfirm] = useState("");
  const [removePassword, setRemovePassword] = useState("");
  const [removeTotp, setRemoveTotp] = useState("");
  const [removeBusy, setRemoveBusy] = useState(false);
  const [removeError, setRemoveError] = useState("");

  const reload = useCallback(async () => {
    const data = await getAccount();
    setAccount(data.account);
    setSessionActivity(data.session?.last_activity || data.session?.created_at || "");
    setUser(data.account);
  }, [setUser]);

  useEffect(() => {
    reload().catch(() => setError("Could not load account."));
  }, [reload]);

  const onChangeUsername = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      await changeUsername(newUsername);
      setShowUsername(false);
      setNewUsername("");
      setMsg("Username updated.");
      await reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Update failed.");
    }
  };

  const onChangePassword = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      await changePassword({ current_password: currentPassword, password: newPassword, confirm_password: confirmPassword });
      await authSignOut();
      navigate("/signin", { replace: true });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Password change failed.");
    }
  };

  const onStartTotp = async () => {
    setError("");
    try {
      const data = await totpSetup();
      setSetupToken(data.setup_token);
      setManualKey(data.manual_key);
      setQrBase64(data.qr_png_base64);
      setShowTotpSetup(true);
      setTotpCode("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not start 2FA setup.");
    }
  };

  const onVerifyTotpSetup = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      await totpVerifySetup({ setup_token: setupToken, code: totpCode });
      setShowTotpSetup(false);
      setManualKey("");
      setQrBase64("");
      setMsg("Two-factor authentication enabled.");
      await reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Invalid code.");
    }
  };

  const onDisableTotp = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      await totpDisable({ current_password: currentPassword, code: totpCode });
      setShowTotpDisable(false);
      setCurrentPassword("");
      setTotpCode("");
      setMsg("Two-factor authentication disabled.");
      await reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not disable 2FA.");
    }
  };

  const onSignOut = async () => {
    await signOut().catch(() => {});
    await authSignOut();
    navigate("/signin", { replace: true });
  };

  const onRemoveAccount = async (e: FormEvent) => {
    e.preventDefault();
    setRemoveError("");
    setRemoveBusy(true);
    try {
      await removeAccount({
        confirmation: removeConfirm,
        current_password: removePassword,
        totp_code: account?.totp_enabled ? removeTotp : undefined,
      });
      clearAccount();
      setShowRemoveDialog(false);
      navigate("/signup", { replace: true });
    } catch (err: unknown) {
      setRemoveError(err instanceof Error ? err.message : "Account was not removed. Please try again.");
    } finally {
      setRemoveBusy(false);
    }
  };

  const removeReady =
    removeConfirm === "DELETE" &&
    removePassword.length > 0 &&
    (!account?.totp_enabled || removeTotp.length >= 6);

  if (!account) {
    return <p className="text-[13px] text-muted">Loading account…</p>;
  }

  return (
    <section>
      <PanelHead title="Authentication" sub="Manage your owner account, password, and two-factor authentication." />

      {msg && <p className="text-[12px] text-accent mb-3">{msg}</p>}
      {error && <p className="text-[12px] text-red-500 mb-3">{error}</p>}

      <SectionTitle>Account</SectionTitle>
      <div className="rounded-md border border-border bg-panel/40 px-4 py-3">
        <FieldRow label="Username" value={account.username} />
        <FieldRow label="User" value={account.email} />
        <FieldRow label="Created" value={new Date(account.created_at).toLocaleString()} />
        <FieldRow label="2FA status" value={account.totp_enabled ? "Enabled" : "Not enabled"} />
      </div>
      <div className="flex flex-wrap gap-2 mt-3">
        <SmallButton onClick={() => { setShowUsername(true); setNewUsername(account.username); setShowPassword(false); }}>Change Username</SmallButton>
        <SmallButton onClick={() => { setShowPassword(true); setShowUsername(false); }}>Change Password</SmallButton>
      </div>

      {showUsername && (
        <form onSubmit={onChangeUsername} className="mt-4 p-4 rounded-md border border-border bg-panel/30 space-y-3 max-w-md">
          <label className="block text-[12px] text-muted">New Username</label>
          <input className={authInputClass} value={newUsername} onChange={(e) => setNewUsername(e.target.value)} required />
          <div className="flex gap-2">
            <button type="submit" className="text-[12px] px-3 py-1.5 rounded-md bg-accent text-white">Save</button>
            <button type="button" className="text-[12px] px-3 py-1.5 rounded-md border border-border text-muted" onClick={() => setShowUsername(false)}>Cancel</button>
          </div>
        </form>
      )}

      {showPassword && (
        <form onSubmit={onChangePassword} className="mt-4 p-4 rounded-md border border-border bg-panel/30 space-y-3 max-w-md">
          <input type="password" placeholder="Current password" className={authInputClass} value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} required />
          <input type="password" placeholder="New password" className={authInputClass} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required />
          <input type="password" placeholder="Confirm new password" className={authInputClass} value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required />
          <div className="flex gap-2">
            <button type="submit" className="text-[12px] px-3 py-1.5 rounded-md bg-accent text-white">Change Password</button>
            <button type="button" className="text-[12px] px-3 py-1.5 rounded-md border border-border text-muted" onClick={() => setShowPassword(false)}>Cancel</button>
          </div>
        </form>
      )}

      <Divider />
      <SectionTitle>Security</SectionTitle>
      <div className="rounded-md border border-border bg-panel/40 px-4 py-3">
        <p className="text-[13px] font-medium text-fg">Two-Factor Authentication</p>
        <p className="text-[12px] text-muted mt-1">Status: {account.totp_enabled ? "Enabled" : "Not enabled"}</p>
        <div className="mt-3">
          {!account.totp_enabled && !showTotpSetup && (
            <SmallButton onClick={onStartTotp}>Set up 2FA</SmallButton>
          )}
          {account.totp_enabled && !showTotpDisable && (
            <SmallButton onClick={() => { setShowTotpDisable(true); setCurrentPassword(""); setTotpCode(""); }} variant="danger">Disable 2FA</SmallButton>
          )}
        </div>
      </div>

      {showTotpSetup && (
        <form onSubmit={onVerifyTotpSetup} className="mt-4 p-4 rounded-md border border-border bg-panel/30 max-w-md space-y-3">
          <p className="text-[13px] text-fg font-medium">Scan this QR code with your authenticator app</p>
          {qrBase64 && (
            <img src={`data:image/png;base64,${qrBase64}`} alt="TOTP QR code" className="mx-auto w-48 h-48 rounded-md border border-border bg-white p-2" />
          )}
          <div>
            <p className="text-[12px] text-muted">Can&apos;t scan? Manual setup key:</p>
            <code className="text-[12px] break-all text-fg">{manualKey}</code>
          </div>
          <input type="text" inputMode="numeric" placeholder="6-digit code" className={authInputClass + " tracking-widest text-center"} value={totpCode} onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, "").slice(0, 6))} maxLength={6} required />
          <button type="submit" className="text-[12px] px-3 py-1.5 rounded-md bg-accent text-white w-full" disabled={totpCode.length < 6}>Verify &amp; Enable</button>
        </form>
      )}

      {showTotpDisable && (
        <form onSubmit={onDisableTotp} className="mt-4 p-4 rounded-md border border-border bg-panel/30 max-w-md space-y-3">
          <p className="text-[12px] text-muted">Enter your current password and authenticator code to disable 2FA.</p>
          <input type="password" placeholder="Current password" className={authInputClass} value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} required />
          <input type="text" inputMode="numeric" placeholder="6-digit code" className={authInputClass + " tracking-widest text-center"} value={totpCode} onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, "").slice(0, 6))} maxLength={6} required />
          <div className="flex gap-2">
            <button type="submit" className="text-[12px] px-3 py-1.5 rounded-md bg-accent text-white">Disable 2FA</button>
            <button type="button" className="text-[12px] px-3 py-1.5 rounded-md border border-border text-muted" onClick={() => setShowTotpDisable(false)}>Cancel</button>
          </div>
        </form>
      )}

      <Divider />
      <SectionTitle>Sessions</SectionTitle>
      <div className="rounded-md border border-border bg-panel/40 px-4 py-3">
        <p className="text-[13px] font-medium text-fg">Current session</p>
        {sessionActivity && (
          <p className="text-[12px] text-muted mt-1">Last activity: {new Date(sessionActivity).toLocaleString()}</p>
        )}
        <div className="mt-3">
          <SmallButton onClick={onSignOut}>Sign Out</SmallButton>
        </div>
      </div>

      <Divider />
      <SectionTitle>Danger Zone</SectionTitle>
      <div className="rounded-md border border-red-500/30 bg-red-500/5 px-4 py-3">
        <p className="text-[13px] font-medium text-fg">Remove Account</p>
        <p className="text-[12px] text-muted mt-1 max-w-lg">
          Permanently delete the owner account and all account-owned data. This action cannot be undone.
        </p>
        <div className="mt-3">
          <SmallButton
            variant="danger"
            onClick={() => {
              setShowRemoveDialog(true);
              setRemoveConfirm("");
              setRemovePassword("");
              setRemoveTotp("");
              setRemoveError("");
            }}
          >
            Remove Account
          </SmallButton>
        </div>
      </div>

      {showRemoveDialog && (
        <div className="fixed inset-0 z-50 bg-ink/40 grid place-items-center p-4">
          <div className="w-full max-w-md rounded-md border border-border bg-panel shadow-2xl p-6">
            <h2 className="text-[17px] font-semibold text-fg">Remove Account?</h2>
            <p className="text-[13px] text-muted mt-2 leading-relaxed">
              This will permanently delete your account, authentication credentials, sessions, 2FA configuration,
              and all application data associated with this account. This action cannot be undone.
            </p>
            <form onSubmit={onRemoveAccount} className="mt-5 space-y-3">
              <div>
                <label className="block text-[12px] text-muted mb-1.5">Type DELETE to confirm</label>
                <input
                  className={authInputClass}
                  value={removeConfirm}
                  onChange={(e) => setRemoveConfirm(e.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                />
              </div>
              <input
                type="password"
                placeholder="Current password"
                className={authInputClass}
                value={removePassword}
                onChange={(e) => setRemovePassword(e.target.value)}
                required
              />
              {account.totp_enabled && (
                <input
                  type="text"
                  inputMode="numeric"
                  placeholder="6-digit authenticator code"
                  className={authInputClass + " tracking-widest text-center"}
                  value={removeTotp}
                  onChange={(e) => setRemoveTotp(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  maxLength={6}
                  required
                />
              )}
              {removeError && <p className="text-[12px] text-red-500">{removeError}</p>}
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  className="text-[12px] px-3 py-1.5 rounded-md border border-border text-muted"
                  onClick={() => setShowRemoveDialog(false)}
                  disabled={removeBusy}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="text-[12px] px-3 py-1.5 rounded-md bg-red-600 text-white disabled:opacity-40"
                  disabled={!removeReady || removeBusy}
                >
                  Remove Account
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </section>
  );
}
