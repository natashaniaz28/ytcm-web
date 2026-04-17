import { useState, useEffect, useRef } from 'react'
import { watchJob } from '../api'

export function useJob() {
  const [jobState, setJobState] = useState(null) // null | { status, progress, total, result, error, ... }
  const cleanupRef = useRef(null)

  function startWatching(jobId) {
    if (cleanupRef.current) cleanupRef.current()
    setJobState({ status: 'pending', jobId })
    const cleanup = watchJob(jobId, (msg) => {
      console.log("WS MESSAGE:", msg)
      setJobState((prev) => ({ ...prev, ...msg, jobId }))
    })
    cleanupRef.current = cleanup
  }

  function reset() {
    if (cleanupRef.current) cleanupRef.current()
    setJobState(null)
  }

  useEffect(() => {
    return () => {
      if (cleanupRef.current) cleanupRef.current()
    }
  }, [])

  const isRunning = jobState?.status === 'running' || jobState?.status === 'pending'
  const isDone = jobState?.status === 'done'
  const isError = jobState?.status === 'error'

  return { jobState, startWatching, reset, isRunning, isDone, isError }
}
