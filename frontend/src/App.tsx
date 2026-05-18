import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Layout } from './components/layout/Layout'
import { Dashboard } from './pages/Dashboard'
import { Approvals } from './pages/Approvals'
import { ApprovalDetail } from './pages/ApprovalDetail'
import { History } from './pages/History'
import { SettingsPage } from './pages/Settings'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/approvals/:sessionId" element={<ApprovalDetail />} />
          <Route path="/history" element={<History />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
