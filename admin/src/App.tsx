import { Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/hooks/useAuth";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Layout } from "@/components/Layout";
import Login from "@/pages/Login";
import Users from "@/pages/Users";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <Layout>
                <Routes>
                  <Route path="/" element={<Navigate to="/data-sources" replace />} />
                  <Route path="/data-sources" element={<div>数据源管理（待实现）</div>} />
                  <Route path="/sync-logs" element={<div>同步监控（待实现）</div>} />
                  <Route path="/customizations" element={<div>Customization（待实现）</div>} />
                  <Route path="/llm-providers" element={<div>LLM 供应商（待实现）</div>} />
                  <Route path="/conversations" element={<div>对话审查（待实现）</div>} />
                  <Route path="/users" element={<Users />} />
                </Routes>
              </Layout>
            </ProtectedRoute>
          }
        />
      </Routes>
    </AuthProvider>
  );
}
