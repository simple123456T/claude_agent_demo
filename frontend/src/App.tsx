import { useState } from "react";
import {
  ApiOutlined,
  LineChartOutlined,
  LogoutOutlined,
  MessageOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Button, Layout, Menu, Skeleton, Tag, Typography } from "antd";
import { AuthProvider, useAuth } from "./auth";
import { AskPage } from "./pages/AskPage";
import { LoginScreen } from "./pages/LoginScreen";
import { OverviewPage } from "./pages/OverviewPage";
import { roleLabel } from "./utils/roles";

const { Header, Sider, Content } = Layout;
type Page = "ask" | "overview";

function Shell() {
  const { me, logout } = useAuth();
  const [page, setPage] = useState<Page>("ask");

  const roles = [
    ...(me?.is_org_admin ? ["组织管理员"] : []),
    ...(me?.workspaces ?? [])
      .filter((w) => w.role)
      .map((w) => roleLabel(w.role)),
  ];

  return (
    <Layout className="app-shell">
      <Sider breakpoint="lg" collapsedWidth="0" width={236} className="app-sider">
        <div className="brand">
          <div className="brand-mark">
            <LineChartOutlined />
          </div>
          <div>
            <strong>DataAgent</strong>
            <span>企业智能问数</span>
          </div>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[page]}
          onClick={({ key }) => setPage(key as Page)}
          items={[
            { key: "ask", icon: <MessageOutlined />, label: "智能问数" },
            { key: "overview", icon: <ApiOutlined />, label: "系统概览" },
          ]}
        />
        <div className="sider-foot">内网部署 · 数据不出域</div>
      </Sider>
      <Layout>
        <Header className="app-header">
          <Typography.Text strong>{page === "ask" ? "智能问数" : "系统概览"}</Typography.Text>
          <div className="user-box">
            <UserOutlined />
            <span className="user-name">{me?.display_name ?? me?.subject}</span>
            {[...new Set(roles)].slice(0, 2).map((role) => (
              <Tag key={role} color="blue">
                {role}
              </Tag>
            ))}
            <Button type="text" size="small" icon={<LogoutOutlined />} onClick={logout}>
              退出
            </Button>
          </div>
        </Header>
        <Content className={`app-content ${page === "ask" ? "app-content-ask" : ""}`}>
          {page === "ask" ? <AskPage /> : <OverviewPage />}
        </Content>
      </Layout>
    </Layout>
  );
}

function Gate() {
  const { status } = useAuth();
  if (status === "loading") {
    return (
      <div className="boot">
        <Skeleton active paragraph={{ rows: 4 }} />
      </div>
    );
  }
  return status === "authenticated" ? <Shell /> : <LoginScreen />;
}

export default function App() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  );
}
