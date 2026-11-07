// 来源：21st Shining Text，@preetsuthar17，demo 1865。仅补 strict 类型与深色底字对比度；浅色样式及动效不变。
"use client" 

import * as React from "react"

import { motion } from "motion/react";
 
export function ShiningText({text}: {text: string}) {
  return (
    <motion.h1
      className="bg-[linear-gradient(110deg,#404040,35%,#fff,50%,#404040,75%,#404040)] dark:bg-[linear-gradient(110deg,#a3a3a3,35%,#fff,50%,#a3a3a3,75%,#a3a3a3)] bg-[length:200%_100%] bg-clip-text text-base font-regular text-transparent"
      initial={{ backgroundPosition: "200% 0" }}
      animate={{ backgroundPosition: "-200% 0" }}
      transition={{
        repeat: Infinity,
        duration: 2,
        ease: "linear",
      }}
    >
      {text}
    </motion.h1>
  );
}
