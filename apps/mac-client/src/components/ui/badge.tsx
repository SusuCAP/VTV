import { type VariantProps, cva } from "class-variance-authority";
import * as React from "react";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold transition-colors",
  {
    variants: {
      variant: {
        default: "bg-indigo-900/60 text-indigo-300 border border-indigo-700/50",
        secondary: "bg-slate-800 text-slate-300 border border-slate-700",
        destructive: "bg-red-900/60 text-red-300 border border-red-700/50",
        success: "bg-green-900/60 text-green-300 border border-green-700/50",
        warning: "bg-amber-900/60 text-amber-300 border border-amber-700/50",
        outline: "text-slate-300 border border-[#2a3347]",
        info: "bg-blue-900/60 text-blue-300 border border-blue-700/50",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
