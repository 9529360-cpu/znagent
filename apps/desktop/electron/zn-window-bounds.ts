export type ZnRectangle = {
  x: number
  y: number
  width: number
  height: number
}

export function fitZnWindowToWorkArea(bounds: ZnRectangle, workArea: ZnRectangle): ZnRectangle {
  const width = Math.min(bounds.width, workArea.width)
  const height = Math.min(bounds.height, workArea.height)
  const maxX = workArea.x + workArea.width - width
  const maxY = workArea.y + workArea.height - height

  return {
    x: Math.min(Math.max(bounds.x, workArea.x), maxX),
    y: Math.min(Math.max(bounds.y, workArea.y), maxY),
    width,
    height
  }
}
