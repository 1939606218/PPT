import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import AppLayout from './components/AppLayout'
import ProtectedRoute from './components/ProtectedRoute'
import Login from './pages/Login'
import Register from './pages/Register'
import Score from './pages/Score'
import BatchScore from './pages/BatchScore'
import History from './pages/History'
import AllHistory from './pages/admin/AllHistory'
import UserManagement from './pages/admin/UserManagement'
import PromptEditor from './pages/admin/PromptEditor'
import LLMSettings from './pages/admin/LLMSettings'
import ScoringConfig from './pages/admin/ScoringConfig'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />

        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            <Route path="/score" element={<Score />} />
            <Route path="/batch" element={<BatchScore />} />
            <Route path="/history" element={<History />} />
            <Route element={<ProtectedRoute requireAdmin />}>
              <Route path="/admin/history" element={<AllHistory />} />
              <Route path="/admin/users" element={<UserManagement />} />
              <Route path="/admin/prompts" element={<PromptEditor />} />
              <Route path="/admin/llm-settings" element={<LLMSettings />} />
              <Route path="/admin/scoring-config" element={<ScoringConfig />} />
            </Route>
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/score" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
