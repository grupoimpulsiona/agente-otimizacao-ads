import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Layout } from './components/layout/Layout'
import { Dashboard } from './pages/Dashboard'
import { Approvals } from './pages/Approvals'
import { ApprovalDetail } from './pages/ApprovalDetail'
import { History } from './pages/History'
import { SettingsPage } from './pages/Settings'
import { GoogleAdsPage } from './pages/GoogleAdsPage'
import { MetaAdsPage } from './pages/MetaAdsPage'
import { Relatorios } from './pages/Relatorios'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/approvals/:sessionId" element={<ApprovalDetail />} />
          <Route path="/google-ads" element={<GoogleAdsPage />} />
          <Route path="/meta-ads" element={<MetaAdsPage />} />
          <Route path="/relatorios" element={<Relatorios />} />
          <Route path="/history" element={<History />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
