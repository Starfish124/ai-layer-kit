import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Gebouwd onder /flow/ zodat controlroom.py de dist rechtstreeks kan serveren.
// In dev praat Vite door naar de Python-server voor de feiten.
export default defineConfig({
  plugins: [react()],
  base: '/flow/',
  build: { outDir: 'dist', emptyOutDir: true },
  server: { proxy: { '/flow.json': 'http://127.0.0.1:7415', '/events': 'http://127.0.0.1:7415', '/meet.json': 'http://127.0.0.1:7415' } },
})
