export const ROLE_LABELS: Record<string, string> = {
  workspace_admin: "工作区管理员",
  steward: "数据负责人",
  analyst: "分析师",
  viewer: "查看者",
};

export const roleLabel = (role: string | null): string =>
  role ? (ROLE_LABELS[role] ?? role) : "无角色";
