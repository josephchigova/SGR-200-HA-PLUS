import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { dropSessionIfBrowserWasClosed } from './session'
import App from './App.jsx'

dropSessionIfBrowserWasClosed()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
