import { useEffect, useState } from "react";
import { LineChartOutlined, UserOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Skeleton, Typography } from "antd";
import { ApiError } from "../api/client";
import { fetchAuthConfig } from "../api/query";
import type { AuthConfig } from "../api/types";
import { useAuth } from "../auth";

export function LoginScreen() {
  const { login, error } = useAuth();
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  useEffect(() => {
    fetchAuthConfig()
      .then(setConfig)
      .catch((failure: unknown) =>
        setLoadError(failure instanceof ApiError ? failure.message : "无法读取登录配置"),
      );
  }, []);

  const enter = async (subject: string) => {
    setPending(subject);
    await login(subject);
    setPending(null);
  };

  return (
    <main className="login">
      <div className="login-card">
        <div className="login-brand">
          <div className="brand-mark">
            <LineChartOutlined />
          </div>
          <div>
            <strong>DataAgent</strong>
            <span>企业智能问数</span>
          </div>
        </div>

        {error && <Alert className="login-alert" type="warning" showIcon message={error} />}
        {loadError && (
          <Alert
            className="login-alert"
            type="error"
            showIcon
            message="后端暂不可用"
            description={`${loadError}。请确认 FastAPI 已在 127.0.0.1:8001 启动。`}
          />
        )}
        {!config && !loadError && <Skeleton active paragraph={{ rows: 3 }} />}

        {config?.mode === "dev" && (
          <>
            <Typography.Title level={4}>选择开发身份登录</Typography.Title>
            <Typography.Paragraph type="secondary">
              仅限本机开发使用，接入企业 SSO 后自动停用。三个身份的权限不同，可以分别体验。
            </Typography.Paragraph>
            <div className="identity-list">
              {config.dev_identities.map((identity) => (
                <Card
                  key={identity.subject}
                  hoverable
                  size="small"
                  className="identity-card"
                  onClick={() => pending === null && void enter(identity.subject)}
                >
                  <UserOutlined className="identity-icon" />
                  <div className="identity-text">
                    <strong>{identity.label}</strong>
                    <span>{identity.description}</span>
                  </div>
                  <Button type="primary" size="small" loading={pending === identity.subject}>
                    进入
                  </Button>
                </Card>
              ))}
            </div>
          </>
        )}

        {config?.mode === "oidc" && (
          <Alert
            type="info"
            showIcon
            message="已配置企业 SSO"
            description="浏览器端的 SSO 登录流程（授权码 + PKCE）还在开发中，目前只能通过 API 携带令牌访问。"
          />
        )}
        {config?.mode === "unconfigured" && (
          <Alert
            type="warning"
            showIcon
            message="后端未配置身份认证"
            description="请在 .env 中配置 OIDC_ISSUER，或在本机开发时设置 DEV_AUTH_ENABLED=true 并运行 python -m app.demo.seed。"
          />
        )}
      </div>
    </main>
  );
}
