import { BrowserRouter, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { Replay } from './routes/Replay'
import { Live } from './routes/Live'

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex flex-col h-screen">
        <header className="flex items-center gap-4 px-4 py-2 border-b border-slate-700 bg-slate-950/80">
          <h1 className="text-sm font-semibold text-slate-100">七圣召唤 · 对战</h1>
          <nav className="flex gap-2">
            <NavLink
              to="/replay"
              className={({ isActive }) =>
                `text-xs px-2 py-1 rounded ${
                  isActive
                    ? 'bg-sky-500/20 text-sky-200'
                    : 'text-slate-400 hover:text-slate-200'
                }`
              }
            >
              回放分析
            </NavLink>
            <NavLink
              to="/live"
              className={({ isActive }) =>
                `text-xs px-2 py-1 rounded ${
                  isActive
                    ? 'bg-sky-500/20 text-sky-200'
                    : 'text-slate-400 hover:text-slate-200'
                }`
              }
            >
              模型对战
            </NavLink>
          </nav>
        </header>
        <div className="flex-1 overflow-hidden">
          <Routes>
            <Route path="/" element={<Navigate to="/live" replace />} />
            <Route path="/replay" element={<Replay />} />
            <Route path="/live" element={<Live />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  )
}
