import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ReactFlow, Background, Controls, MiniMap, useNodesState, useEdgesState } from '@xyflow/react'
import Blok from './Blok.jsx'

// Posities worden uitgerekend uit (laag, rij) en nooit bewaard: slepen mag,
// herladen zet alles terug. Een kaart die je met de hand hebt gelegd is binnen
// een week gelogen (ADR-005 / ADR-007).
const W = 220, H = 74, GX = 90, GY = 18, PAD = 30
const nodeTypes = { blok: Blok }

function leg(data, live, q) {
  const tekst = n => [n.naam, n.doc, n.soort, n.module, ...(n.bronnen || []), ...(n.velden || []), ...(n.uitkomsten || [])].join(' ').toLowerCase()
  const nodes = data.nodes.map(n => ({
    id: n.id, type: 'blok',
    position: { x: PAD + n.laag * (W + GX), y: PAD + n.rij * (H + GY) },
    data: { n, live: live[n.module || (n.id.startsWith('uit:') ? n.id.slice(4) : null)] || null,
            dim: !!q && !tekst(n).includes(q) },
  }))
  const edges = data.edges.map(([a, b]) => ({ id: a + '→' + b, source: a, target: b, animated: false,
    style: { stroke: 'var(--faint)' } }))
  return { nodes, edges }
}

export default function App() {
  const params = new URLSearchParams(location.search)
  const [module, setModule] = useState(params.get('module') || null)
  const [run, setRun] = useState(params.get('run') === '1')
  const [data, setData] = useState(null)
  const [gekozen, setGekozen] = useState(null)
  const [q, setQ] = useState('')
  const [live, setLive] = useState({})       // module → {stand, tekst}
  const [feed, setFeed] = useState([])       // laatste gebeurtenissen
  const [ketens, setKetens] = useState({})
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges] = useEdgesState([])
  const herlaad = useRef(0)

  // --export bakt alle niveaus in als window.STROOM; dan is er geen server en geen stroom.
  const INLINE = window.STROOM || null
  const laad = useCallback(async () => {
    if (INLINE) { setData(INLINE[module || '']); setGekozen(null); return }
    const r = await fetch('/flow.json?' + (module ? 'module=' + encodeURIComponent(module) + '&' : '') + (run ? 'run=1' : ''))
    setData(await r.json()); setGekozen(null)
  }, [module, run, INLINE])
  useEffect(() => { laad() }, [laad, herlaad.current])

  useEffect(() => {
    if (!data) return
    const { nodes, edges } = leg(data, live, q.trim().toLowerCase())
    setNodes(nodes); setEdges(edges)
  }, [data, live, q, setNodes, setEdges])

  // De feitenstroom. Elke gebeurtenis is iets dat ergens gemeten is; het
  // canvas kleurt, oordeelt niet.
  useEffect(() => {
    if (INLINE) return
    const es = new EventSource('/events')
    es.onmessage = ev => {
      const e = JSON.parse(ev.data)
      setFeed(f => [e, ...f].slice(0, 12))
      if (e.soort === 'vk' && e.module) {
        const stand = e.ok === null ? 'bezig' : e.ok ? 'groen' : 'rood'
        setLive(l => ({ ...l, [e.module]: { stand, tekst: e.tekst } }))
      }
      if (e.soort === 'keten') setKetens(k => ({ ...k, [e.keten]: e.tekst }))
      if (e.soort === 'meting') { herlaad.current++; laad() }
    }
    return () => es.close()
  }, [laad, INLINE])

  const by = useMemo(() => Object.fromEntries((data?.nodes || []).map(n => [n.id, n])), [data])
  const n = gekozen ? by[gekozen] : null

  return (
    <div className="app">
      <header>
        <span className="eyebrow">Stroom</span>
        <b>{data?.titel || '…'}{data?.fout ? ' — ' + data.fout : ''}</b>
        {module && <a onClick={() => setModule(null)}>← overzicht</a>}
        <input placeholder="filter: Exact-export, Mail.Read, ontbreekt…" value={q} onChange={e => setQ(e.target.value)} />
        <label><input type="checkbox" checked={run} onChange={e => setRun(e.target.checked)} /> tests draaien</label>
        <span className="hint">klik = code · dubbelklik systeem = naar binnen · sleep = kijken, niet bewaren</span>
      </header>
      <div className="canvas">
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange}
          onNodeClick={(_, nd) => setGekozen(nd.id)}
          onNodeDoubleClick={(_, nd) => { const x = by[nd.id]; if (x?.soort === 'systeem' && x.gebouwd) setModule(x.module) }}
          fitView minZoom={0.2} maxZoom={2.5} proOptions={{ hideAttribution: true }}>
          <Background gap={24} color="#e3e7ee" />
          <MiniMap pannable zoomable />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <aside>
        {n ? <Paneel n={n} live={live} /> : <p className="leeg">Klik op een blok.</p>}
        <h4>Nu</h4>
        {feed.length === 0 && <p className="leeg">Nog niets gebeurd sinds het openen.</p>}
        <ul className="feed">{feed.map((e, i) => <li key={i} className={e.ok === false ? 'rood' : e.ok ? 'groen' : ''}>
          <span className="t">{e.t.slice(11, 19)}</span> <span className="s">{e.soort}</span> {e.tekst}</li>)}</ul>
        {Object.keys(ketens).length > 0 && <><h4>Ketens</h4><ul className="feed">{Object.values(ketens).map((t, i) => <li key={i}>{t}</li>)}</ul></>}
      </aside>
    </div>
  )
}

function Paneel({ n, live }) {
  if (n.soort === 'functie' || n.soort === 'data') {
    const dek = n.geraakt === true ? ' · door de test geraakt' : n.geraakt === false ? ' · door geen test geraakt' : ''
    return <><h3>{n.naam}</h3><div className="meta">{n.soort} · regel {n.regels[0]}–{n.regels[1]}{dek}</div><pre>{n.code}</pre></>
  }
  const l = live[n.module]
  return <>
    <h3>{n.naam}</h3><div className="meta">{n.soort}</div>
    <dl>
      {n.soort === 'systeem' && <><dt>permissie</dt><dd>{n.doc || '—'}</dd></>}
      {n.bronnen?.length > 0 && <><dt>leest</dt><dd>{n.bronnen.join(', ')}</dd></>}
      {n.velden?.length > 0 && <><dt>velden (gemeten)</dt><dd>{n.velden.map(v => <code key={v}>{v}</code>)}</dd></>}
      {n.uitkomsten?.length > 0 && <><dt>meldt</dt><dd>{n.uitkomsten.map(v => <code key={v}>{v}</code>)}</dd></>}
      {n.residentie && <><dt>data staat</dt><dd>{n.residentie}</dd></>}
      {n.verlaat_tenant && <><dt>verlaat tenant</dt><dd>{n.verlaat_tenant}</dd></>}
      {n.module && <><dt>module</dt><dd><code>{n.module}.py</code> {n.gebouwd ? '— dubbelklik om naar binnen te gaan' : '— nog niet gebouwd'}</dd></>}
      {l && <><dt>live</dt><dd className={l.stand}>{l.tekst}</dd></>}
    </dl>
  </>
}
