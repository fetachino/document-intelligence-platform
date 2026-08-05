import React, { useState } from 'react'

export default function App() {
  const [file, setFile] = useState<File | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  async function upload() {
    if (!file) return
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch('/api/v1/documents/upload', { method: 'POST', body: fd })
    if (res.ok) setMessage('Upload successful')
    else setMessage('Upload failed')
  }

  return (
    <div style={{ padding: 20 }}>
      <h1>Document Intelligence Platform (Milestone 1)</h1>
      <input type="file" onChange={(e) => setFile(e.target.files ? e.target.files[0] : null)} />
      <button onClick={upload}>Upload</button>
      {message && <p>{message}</p>}
    </div>
  )
}
