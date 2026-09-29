function bfs(adj, from, to) {
  const prev = new Map([[from, null]]);
  const queue = [from];
  while (queue.length) {
    const cur = queue.shift();
    if (cur === to) break;
    for (const nxt of adj.get(cur) || []) {
      if (!prev.has(nxt)) {
        prev.set(nxt, cur);
        queue.push(nxt);
      }
    }
  }
  if (!prev.has(to)) return null;
  const path = [];
  for (let n = to; n != null; n = prev.get(n)) path.unshift(n);
  return path;
}

/**
 * Trace how value moved between two addresses of the investigation graph.
 * Prefers a path that follows the direction of funds (from -> to), then funds
 * arriving (to -> from), and only then any connection ignoring direction.
 * Returns { path, mode } where mode is 'outflow' | 'inflow' | 'linked'.
 */
export function tracePath(graph, from, to) {
  if (!graph || !from || !to || from === to) return { path: [], mode: null };
  const fwd = new Map();
  const rev = new Map();
  const undirected = new Map();
  const add = (m, a, b) => { if (!m.has(a)) m.set(a, []); m.get(a).push(b); };
  for (const e of graph.edges) {
    const { source, target, kind } = e.data;
    if (kind === 'cluster') continue;   // co-spend links are ownership, not value flow
    add(fwd, source, target);
    add(rev, target, source);
    add(undirected, source, target);
    add(undirected, target, source);
  }
  const out = bfs(fwd, from, to);
  if (out) return { path: out, mode: 'outflow' };
  const inn = bfs(rev, from, to);
  if (inn) return { path: inn, mode: 'inflow' };
  const any = bfs(undirected, from, to);
  return any ? { path: any, mode: 'linked' } : { path: [], mode: null };
}

/** Merge an expansion result into the current graph, de-duplicating nodes and edges by id. */
export function mergeGraph(graph, extra) {
  if (!graph) return extra;
  if (!extra) return graph;
  const nodeIds = new Set(graph.nodes.map((n) => n.data.id));
  const edgeIds = new Set(graph.edges.map((e) => e.data.id || `${e.data.source}->${e.data.target}`));
  return {
    ...graph,
    nodes: [...graph.nodes, ...extra.nodes.filter((n) => !nodeIds.has(n.data.id))],
    edges: [...graph.edges, ...extra.edges.filter((e) => !edgeIds.has(e.data.id || `${e.data.source}->${e.data.target}`))],
  };
}
