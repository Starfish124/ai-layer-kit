import { Handle, Position } from '@xyflow/react'

// Eén blok op het canvas. Alles wat erop staat komt uit /flow.json of /events;
// dit bestand tekent alleen. `live` = de laatste gebeurtenis over deze module.
export default function Blok({ data, selected }) {
  const { n, live, dim } = data
  const soortKlasse = n.soort + (n.soort === 'systeem' && !n.gebouwd ? ' niet' : '')
  const badge = n.geraakt === true ? <span className="badge ja">✓ test</span>
              : n.geraakt === false ? <span className="badge nee">○ geen test</span> : null
  const ring = live ? ' live-' + live.stand : ''
  return (
    <div className={'blok ' + soortKlasse + ring + (selected ? ' gekozen' : '') + (dim ? ' dim' : '')}>
      <Handle type="target" position={Position.Left} />
      <div className="kop"><span className="soort">{n.soort}</span>{badge}</div>
      <div className="naam">{n.naam}</div>
      <div className="doc">{n.doc}</div>
      {live && <div className={'live ' + live.stand}>{live.tekst}</div>}
      <Handle type="source" position={Position.Right} />
    </div>
  )
}
