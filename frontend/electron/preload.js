import { contextBridge } from 'electron'
import { versions } from 'process'

contextBridge.exposeInMainWorld('api', {
  versions: {
    node: versions.node,
    chrome: versions.chrome,
    electron: versions.electron,
  },
})
