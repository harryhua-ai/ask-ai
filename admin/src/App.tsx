import { Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/hooks/useAuth";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Layout } from "@/components/Layout";
import Login from "@/pages/Login";
import Users from "@/pages/Users";
import DataSources from "@/pages/DataSources";
import SyncLogs from "@/pages/SyncLogs";
import Customizations from "@/pages/Customizations";
import LLMProviders from "@/pages/LLMProviders";
import Conversations from "@/pages/Conversations";
import AnswerOverrides from "@/pages/AnswerOverrides";
import Analytics from "@/pages/Analytics";

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
                  <Route path="/data-sources" element={<DataSources />} />
                  <Route path="/sync-logs" element={<SyncLogs />} />
                  <Route path="/customizations" element={<Customizations />} />
                  <Route path="/llm-providers" element={<LLMProviders />} />
                  <Route path="/conversations" element={<Conversations />} />
                  <Route path="/answer-overrides" element={<AnswerOverrides />} />
                  <Route path="/analytics" element={<Analytics />} />
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
