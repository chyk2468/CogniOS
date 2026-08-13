import type { ReactNode } from "react";

export function AuthLayout({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-bg grid place-items-center px-4 py-10">
      <div className="w-full max-w-[420px] rounded-md border border-border bg-panel shadow-2xl p-8">
        <h1 className="text-[19px] font-semibold text-fg">{title}</h1>
        {subtitle && <p className="text-[13px] text-muted mt-1 mb-6">{subtitle}</p>}
        {!subtitle && <div className="mb-6" />}
        {children}
      </div>
    </div>
  );
}

export function AuthField({
  label,
  id,
  error,
  children,
}: {
  label: string;
  id: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-4">
      <label htmlFor={id} className="block text-[12px] font-medium text-muted mb-1.5">
        {label}
      </label>
      {children}
      {error && <p className="text-[12px] text-red-500 mt-1">{error}</p>}
    </div>
  );
}

export const authInputClass =
  "w-full px-3 py-2 rounded-md border border-border bg-bg text-fg text-[13px] outline-none focus:border-accent";

export function AuthButton({
  children,
  disabled,
  type = "submit",
}: {
  children: React.ReactNode;
  disabled?: boolean;
  type?: "submit" | "button";
}) {
  return (
    <button
      type={type}
      disabled={disabled}
      className="w-full mt-2 px-4 py-2.5 rounded-md bg-accent text-white text-[13px] font-medium disabled:opacity-50"
    >
      {children}
    </button>
  );
}

export function AuthLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <a href={to} className="text-accent hover:underline text-[13px]">
      {children}
    </a>
  );
}
