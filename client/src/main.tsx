import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './i18n'
import './index.css'
import './dashboard/theme-light.css'
import App from './App.tsx'
import { AuthProvider } from './auth/AuthContext'
import { LocaleProvider } from './lib/locale'
import { applyStoredTheme } from './dashboard/ThemeToggle'

applyStoredTheme()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LocaleProvider>
      <AuthProvider>
        <App />
      </AuthProvider>
    </LocaleProvider>
  </StrictMode>,
)
