import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Dashboard   from './pages/Dashboard'
import SearchPage  from './pages/Search'
import DownloadPage from './pages/Download'
import EnrichPage  from './pages/Enrich'
import FilterPage  from './pages/Filter'
import TubeScopePage from './pages/TubeScope'
import TubeTalkPage  from './pages/TubeTalk'
import TubeGraphPage from './pages/TubeGraph'
import ExportPage  from './pages/Export'
import SettingsPage from './pages/Settings'

export default function App() {
  return (
    <BrowserRouter>
      {/* Background orbs */}
      <div className="orb w-96 h-96 bg-acid-500/5 top-[-8rem] left-[10rem]" />
      <div className="orb w-72 h-72 bg-teal-500/4 bottom-[-4rem] right-[20rem]" />

      <div className="flex min-h-screen">
        <Sidebar />

        {/* Main content — offset by sidebar width */}
        <main className="ml-56 flex-1 min-h-screen">
          <div className="max-w-4xl mx-auto px-8 py-10">
            <Routes>
              <Route path="/"           element={<Dashboard />} />
              <Route path="/search"     element={<SearchPage />} />
              <Route path="/download"   element={<DownloadPage />} />
              <Route path="/enrich"     element={<EnrichPage />} />
              <Route path="/filter"     element={<FilterPage />} />
              <Route path="/tubescope"  element={<TubeScopePage />} />
              <Route path="/tubetalk"   element={<TubeTalkPage />} />
              <Route path="/tubegraph"  element={<TubeGraphPage />} />
              <Route path="/export"     element={<ExportPage />} />
              <Route path="/settings"   element={<SettingsPage />} />
            </Routes>
          </div>
        </main>
      </div>
    </BrowserRouter>
  )
}
