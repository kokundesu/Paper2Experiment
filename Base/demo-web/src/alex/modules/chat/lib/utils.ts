// 来源：beUI loader；仅调整本地 import 路径，保留上游结构、样式与动效。
import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
