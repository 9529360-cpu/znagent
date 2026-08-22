/**
 * ZN desktop ships precompiled renderer/control-plane assets and a separately
 * staged self-contained `zn-runtime`. Returning false keeps electron-builder
 * from re-running a node_modules install/collector inside the packaging hook;
 * the runtime payload is produced by the ZN runtime staging path and included
 * explicitly through `extraResources`.
 */
export default async function beforeBuild() {
  return false
}
