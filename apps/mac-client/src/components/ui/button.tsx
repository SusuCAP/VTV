import { Slot } from "@radix-ui/react-slot";
import { type VariantProps, cva } from "class-variance-authority";
import * as React from "react";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-indigo-500 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-indigo-600 text-white shadow hover:bg-indigo-500",
        destructive: "bg-red-600 text-white shadow-sm hover:bg-red-500",
        outline: "border border-[#2a3347] bg-transparent text-slate-300 shadow-sm hover:bg-[#1c2232] hover:text-white",
        secondary: "bg-[#1c2232] text-slate-300 shadow-sm hover:bg-[#232a3d] hover:text-white",
        ghost: "text-slate-400 hover:bg-[#1c2232] hover:text-white",
        link: "text-indigo-400 underline-offset-4 hover:underline",
        success: "bg-green-700 text-white shadow hover:bg-green-600",
        warning: "bg-amber-700 text-white shadow hover:bg-amber-600",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-7 rounded px-3 text-xs",
        lg: "h-10 rounded-md px-8",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />;
  }
);
Button.displayName = "Button";
export { Button, buttonVariants };
