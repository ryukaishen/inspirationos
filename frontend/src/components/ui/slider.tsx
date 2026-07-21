import * as React from "react";

import { cn } from "@/lib/utils";

export interface SliderProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "value" | "type"> {
  value: number;
  onValueChange: (value: number) => void;
}

/** Native range input, hand-rolled like switch/checkbox — no Radix. */
function Slider({ value, onValueChange, className, ...props }: SliderProps) {
  return (
    <input
      type="range"
      value={value}
      onChange={(event) => onValueChange(Number(event.target.value))}
      className={cn(
        "h-2 w-full cursor-pointer appearance-none rounded-full bg-input accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

export { Slider };
