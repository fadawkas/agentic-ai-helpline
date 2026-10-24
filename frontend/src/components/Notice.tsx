type NoticeProps = { children: string; tone?: "info" | "error" };

export function Notice({ children, tone = "info" }: NoticeProps) {
  return <p className={tone === "error" ? "notice notice-error" : "notice"} role={tone === "error" ? "alert" : "status"}>{children}</p>;
}
