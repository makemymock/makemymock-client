import { useEffect, useRef } from 'react'
import styles from './AWaves.module.css'

export default function AWaves({ className = '', flattenTargetId }) {
  const rootRef = useRef(null)
  const canvasRef = useRef(null)
  const animationRef = useRef(0)
  
  // Tracks exactly where the section is inside the viewport
  const flattenRef = useRef({ startY: Infinity, endY: Infinity })

  const mouseRef = useRef({
    x: -10, y: 0, clientX: -10, clientY: 0, lx: 0, ly: 0, sx: 0, sy: 0, v: 0, vs: 0, a: 0, set: false,
  })
  const linesRef = useRef([])
  const boundingRef = useRef({ width: 0, height: 0, left: 0, top: 0 })

  useEffect(() => {
    const canvas = canvasRef.current
    const root = rootRef.current

    if (!canvas || !root) return undefined
    const ctx = canvas.getContext('2d')
    if (!ctx) return undefined

    // Calculates section position relative to the screen
    const updateFlattenCoords = () => {
      if (!flattenTargetId) return
      const targetEl = document.getElementById(flattenTargetId)
      if (targetEl) {
        const rect = targetEl.getBoundingClientRect()
        // Flatten completely exactly where the section starts on screen
        flattenRef.current.endY = rect.top
        // Start transitioning to flat slightly before it
        flattenRef.current.startY = rect.top - (window.innerHeight * 0.5)
      }
    }

    const setSize = () => {
      const rect = root.getBoundingClientRect()
      const scale = window.devicePixelRatio || 1
      boundingRef.current = rect
      canvas.width = Math.max(1, Math.floor(rect.width * scale))
      canvas.height = Math.max(1, Math.floor(rect.height * scale))
      canvas.style.width = `${rect.width}px`
      canvas.style.height = `${rect.height}px`
      ctx.setTransform(scale, 0, 0, scale, 0, 0)
      updateFlattenCoords()
    }

    const buildLines = (axis) => {
      const { width, height } = boundingRef.current
      const lineGap = 84
      const pointGap = 78
      const oWidth = width + 100
      const oHeight = height + 100
      const totalLines = Math.ceil((axis === 'vertical' ? oWidth : oHeight) / lineGap)
      const totalPoints = Math.ceil((axis === 'vertical' ? oHeight : oWidth) / pointGap)
      const lineStart = (axis === 'vertical' ? width : height) / 2 - (lineGap * totalLines) / 2
      const pointStart = (axis === 'vertical' ? height : width) / 2 - (pointGap * totalPoints) / 2
      const lines = []

      for (let i = 0; i <= totalLines; i += 1) {
        const points = []
        for (let j = 0; j <= totalPoints; j += 1) {
          points.push(
            axis === 'vertical'
              ? { x: lineStart + lineGap * i, y: pointStart + pointGap * j, wave: { x: 0, y: 0 }, cursor: { x: 0, y: 0, vx: 0, vy: 0 } }
              : { x: pointStart + pointGap * j, y: lineStart + lineGap * i, wave: { x: 0, y: 0 }, cursor: { x: 0, y: 0, vx: 0, vy: 0 } }
          )
        }
        lines.push(points)
      }
      return lines
    }

    const setLines = () => {
      linesRef.current = [...buildLines('vertical'), ...buildLines('horizontal')]
    }

    const syncMousePosition = () => {
      const mouse = mouseRef.current
      const rect = root.getBoundingClientRect()
      boundingRef.current = rect
      if (!mouse.set) return
      mouse.x = mouse.clientX - rect.left
      mouse.y = mouse.clientY - rect.top
    }

    const updateMousePosition = (x, y) => {
      const mouse = mouseRef.current
      const rect = root.getBoundingClientRect()
      boundingRef.current = rect
      mouse.clientX = x
      mouse.clientY = y
      mouse.x = x - rect.left
      mouse.y = y - rect.top

      if (!mouse.set) {
        mouse.sx = mouse.x
        mouse.sy = mouse.y
        mouse.lx = mouse.x
        mouse.ly = mouse.y
        mouse.set = true
      }
    }

    const handleResize = () => {
      setSize()
      setLines()
      syncMousePosition()
    }

    const handleScroll = () => {
      syncMousePosition()
      updateFlattenCoords() // Crucial: recalculate on scroll!
    }

    const handleMouseMove = (event) => updateMousePosition(event.clientX, event.clientY)
    const handleTouchMove = (event) => {
      if (!event.touches.length) return
      updateMousePosition(event.touches[0].clientX, event.touches[0].clientY)
    }

    const movePoints = (time) => {
      const lines = linesRef.current
      const mouse = mouseRef.current
      const { startY, endY } = flattenRef.current

      lines.forEach((points) => {
        points.forEach((point) => {
          
          let dampening = 1
          if (flattenTargetId) {
            // Check canvas Y position against the section's screen Y position
            if (point.y >= endY) dampening = 0
            else if (point.y > startY) dampening = 1 - ((point.y - startY) / (endY - startY))
          }

          const waveSeed = Math.sin((point.x + time * 0.02) * 0.0085 + point.y * 0.01)
          const waveTilt = Math.cos((point.y + time * 0.016) * 0.0105 + point.x * 0.008)

          point.wave.x = (waveSeed * 28 + waveTilt * 10) * dampening
          point.wave.y = (waveTilt * 14 + waveSeed * 8) * dampening

          const dx = point.x - mouse.sx
          const dy = point.y - mouse.sy
          const distance = Math.hypot(dx, dy)
          const radius = Math.max(180, mouse.vs)

          if (distance < radius) {
            const strength = 1 - distance / radius
            const force = Math.cos(distance * 0.002) * strength
            point.cursor.vx += Math.cos(mouse.a) * force * radius * mouse.vs * 0.00014
            point.cursor.vy += Math.sin(mouse.a) * force * radius * mouse.vs * 0.00014
          }

          point.cursor.vx += (0 - point.cursor.x) * 0.004
          point.cursor.vy += (0 - point.cursor.y) * 0.004
          point.cursor.vx *= 0.93
          point.cursor.vy *= 0.93
          point.cursor.x += point.cursor.vx * 2.25
          point.cursor.y += point.cursor.vy * 2.25

          point.cursor.x = Math.min(100, Math.max(-100, point.cursor.x))
          point.cursor.y = Math.min(100, Math.max(-100, point.cursor.y))
        })
      })
    }

    const moved = (point, withCursorForce = true) => ({
      x: Math.round((point.x + point.wave.x + (withCursorForce ? point.cursor.x : 0)) * 10) / 10,
      y: Math.round((point.y + point.wave.y + (withCursorForce ? point.cursor.y : 0)) * 10) / 10,
    })

    const drawLines = () => {
      const { width, height } = boundingRef.current
      const computedStyles = window.getComputedStyle(root)
      const wavesLineColor = computedStyles.getPropertyValue('--waves-line-color').trim() || 'rgb(255, 255, 255)'
      const wavesGlowColor = computedStyles.getPropertyValue('--waves-glow-color').trim() || 'rgb(255, 255, 255)'
      const wavesCoreColor = computedStyles.getPropertyValue('--waves-core-color').trim() || 'rgba(255, 255, 255, 0.7)'

      ctx.clearRect(0, 0, width, height)
      ctx.beginPath()
      ctx.strokeStyle = wavesLineColor
      ctx.lineWidth = 0.35
      ctx.shadowColor = wavesGlowColor
      ctx.shadowBlur = 15

      linesRef.current.forEach((points) => {
        const movedPoints = points.map((point, index) => moved(point, index !== points.length - 1))
        ctx.moveTo(movedPoints[0].x, movedPoints[0].y)

        for (let i = 1; i < movedPoints.length - 1; i += 1) {
          const current = movedPoints[i]
          const next = movedPoints[i + 1]
          const midX = (current.x + next.x) / 2
          const midY = (current.y + next.y) / 2
          ctx.quadraticCurveTo(current.x, current.y, midX, midY)
        }

        const last = movedPoints[movedPoints.length - 1]
        ctx.lineTo(last.x, last.y)
      })

      ctx.stroke()
      ctx.shadowBlur = 0
      ctx.strokeStyle = wavesCoreColor
      ctx.lineWidth = 0.55
      ctx.stroke()
    }

    const tick = (time) => {
      const mouse = mouseRef.current
      mouse.sx += (mouse.x - mouse.sx) * 0.1
      mouse.sy += (mouse.y - mouse.sy) * 0.1

      const dx = mouse.x - mouse.lx
      const dy = mouse.y - mouse.ly
      const distance = Math.hypot(dx, dy)
      mouse.v = distance
      mouse.vs += (distance - mouse.vs) * 0.1
      mouse.vs = Math.min(100, mouse.vs)
      mouse.lx = mouse.x
      mouse.ly = mouse.y
      mouse.a = Math.atan2(dy, dx)

      movePoints(time)
      drawLines()

      animationRef.current = window.requestAnimationFrame(tick)
    }

    setSize()
    setLines()
    setTimeout(updateFlattenCoords, 200)

    window.addEventListener('resize', handleResize)
    window.addEventListener('scroll', handleScroll, { passive: true })
    window.addEventListener('mousemove', handleMouseMove)
    root.addEventListener('touchmove', handleTouchMove, { passive: false })

    animationRef.current = window.requestAnimationFrame(tick)

    return () => {
      window.removeEventListener('resize', handleResize)
      window.removeEventListener('scroll', handleScroll)
      window.removeEventListener('mousemove', handleMouseMove)
      root.removeEventListener('touchmove', handleTouchMove)
      window.cancelAnimationFrame(animationRef.current)
    }
  }, [flattenTargetId])

  return (
    <div ref={rootRef} className={`${styles.aWaves} ${className}`.trim()} style={{ width: '100%', height: '100%' }}>
      <canvas ref={canvasRef} className={styles.jsCanvas} style={{ width: '100%', height: '100%' }} />
    </div>
  )
}