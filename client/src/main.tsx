import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './dashboard/theme-light.css'
import App from './App.tsx'
import { AuthProvider } from './auth/AuthContext'
import { applyStoredTheme } from './dashboard/ThemeToggle'

applyStoredTheme()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider>
      <App />
    </AuthProvider>
  </StrictMode>,
)
