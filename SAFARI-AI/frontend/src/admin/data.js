// Data loading for the dashboard: a small stale-while-revalidate cache shared by every section.
//
// A query is `[key, load]`: the key names the request (it encodes every parameter) and `load` runs it.
// Opening a section shows the cached answer at once and refetches in the background when it is older
// than `maxAge`; identical requests in flight are shared; `prefetch` warms a section before it opens;
// mutations call `invalidate` so the next view refetches.
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

const MAX_AGE = 30_000;
const cache = new Map(); // key -> { data, at }
const inflight = new Map(); // key -> Promise
const listeners = new Set();
let lastLoadedAt = null;
// Bumped by refreshAll(): every mounted query refetches, keeping its current data on screen meanwhile.
let epoch = 0;
let refreshedAt = 0;
const epochListeners = new Set();

function remember(key, data) {
  const at = Date.now();
  cache.set(key, { data, at });
  lastLoadedAt = at;
  listeners.forEach((listener) => listener(at));
}

/** Runs `load` once for concurrent callers of the same key and caches the result. */
export function fetchQuery([key, load]) {
  if (inflight.has(key)) return inflight.get(key);
  const promise = load()
    .then((data) => {
      remember(key, data);
      return data;
    })
    .finally(() => inflight.delete(key));
  inflight.set(key, promise);
  return promise;
}

/** Loads a query in the background unless a fresh copy is cached. Errors are ignored here. */
export function prefetch(query, maxAge = MAX_AGE) {
  if (!query) return;
  const hit = cache.get(query[0]);
  if (hit && Date.now() - hit.at < maxAge) return;
  fetchQuery(query).catch(() => {});
}

/** Drops cached answers whose key starts with any of `prefixes` (all of them with no argument). */
export function invalidate(...prefixes) {
  for (const key of [...cache.keys()]) {
    if (!prefixes.length || prefixes.some((prefix) => key.startsWith(prefix))) cache.delete(key);
  }
}

/** Marks every cached answer stale and refetches what is on screen, without clearing it first. */
export function refreshAll() {
  for (const entry of cache.values()) entry.at = 0;
  refreshedAt = Date.now();
  epoch += 1;
  epochListeners.forEach((listener) => listener());
}

/** True for a few seconds after refreshAll(), so loaders can ask the server to recompute. */
export const justRefreshed = () => Date.now() - refreshedAt < 5000;

function subscribeEpoch(listener) {
  epochListeners.add(listener);
  return () => epochListeners.delete(listener);
}

/** Calls `listener(timestamp)` whenever any query finishes loading. Returns an unsubscribe function. */
export function onLoaded(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export const lastLoaded = () => lastLoadedAt;

/**
 * `{ data, error, loading, reload }` for a query. Cached data shows immediately; `loading` is true while
 * a (re)fetch runs, so sections dim the old render instead of flashing a skeleton.
 */
export function useQuery(query, { maxAge = MAX_AGE } = {}) {
  const key = query ? query[0] : null;
  const latest = useRef(query);
  latest.current = query;
  const [state, setState] = useState(() => {
    const hit = key ? cache.get(key) : null;
    return { key, data: hit ? hit.data : null, error: null, loading: Boolean(key) };
  });
  const [tick, setTick] = useState(0);
  const currentEpoch = useSyncExternalStore(subscribeEpoch, () => epoch);

  useEffect(() => {
    if (!key) return undefined;
    let alive = true;
    const hit = cache.get(key);
    const fresh = hit && Date.now() - hit.at < maxAge;
    setState((current) => ({
      key,
      data: hit ? hit.data : current.key === key ? current.data : null,
      error: null,
      loading: !(fresh && tick === 0),
    }));
    if (fresh && tick === 0) return undefined;
    if (tick > 0) cache.delete(key);
    fetchQuery(latest.current)
      .then((data) => alive && setState({ key, data, error: null, loading: false }))
      .catch((error) => alive && setState((current) => ({ ...current, error, loading: false })));
    return () => {
      alive = false;
    };
  }, [key, tick, maxAge, currentEpoch]);

  // Rows from a previous key (say, the last period) stay visible, dimmed, until the new answer arrives.
  return { data: state.data, error: state.error, loading: state.loading, reload: () => setTick((value) => value + 1) };
}

/** Like `useQuery` for a request that should not be cached; reruns when `deps` change. */
export function useLoad(load, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setState((current) => ({ ...current, loading: true }));
    load()
      .then((data) => alive && setState({ data, error: null, loading: false }))
      .catch((error) => alive && setState((current) => ({ data: current.data, error, loading: false })));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { ...state, reload: () => setTick((value) => value + 1) };
}
