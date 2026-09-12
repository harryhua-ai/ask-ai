import { Routes, Route } from "react-router-dom";
import { AuthProvider } from "@/hooks/useAuth";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Layout } from "@/components/Layout";
import { LoginChat } from "@/components/LoginChat";
import { Toaster } from "@/components/ui/toast";
import Login from "@/pages/Login";
import Users from "@/pages/Users";
import DataSources from "@/pages/DataSources";
import DataSourceDetail from "@/pages/DataSourceDetail";
import Customizations from "@/pages/Customizations";
import LLMProviders from "@/pages/LLMProviders";
import Conversations from "@/pages/Conversations";
import AnswerOverrides from "@/pages/AnswerOverrides";
import Analytics from "@/pages/Analytics";
import BusinessOverview from "@/pages/BusinessOverview";
import SalesLeads from "@/pages/SalesLeads";
import SystemInfo from "@/pages/SystemInfo";
import WidgetWorkspace from "@/pages/WidgetWorkspace";

export default function App() {
  return (
    <AuthProvider>
      <LoginChat />
      <Toaster />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <Layout>
                <Routes>
                  <Route path="/" element={<BusinessOverview />} />
                  <Route path="/data-sources" element={<DataSources />} />
                  {/* #50 B1 详情工作面(对 #51 的冻结接口路由,不得更改) */}
                  <Route path="/data-sources/:sourceId" element={<DataSourceDetail />} />
                  <Route path="/customizations" element={<Customizations />} />
                  <Route path="/llm-providers" element={<LLMProviders />} />
                  <Route path="/leads" element={<SalesLeads />} />
                  <Route path="/conversations" element={<Conversations />} />
                  <Route path="/answer-overrides" element={<AnswerOverrides />} />
                  <Route path="/analytics" element={<Analytics />} />
                  <Route path="/users" element={<Users />} />
                  <Route path="/system" element={<SystemInfo />} />
                  <Route path="/widget" element={<WidgetWorkspace />} />
                </Routes>
              </Layout>
            </ProtectedRoute>
          }
        />
      </Routes>
    </AuthProvider>
  );
}
