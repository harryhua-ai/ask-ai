import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground",
        secondary: "bg-secondary text-secondary-foreground",
        success: "bg-green-100 text-green-800",
        // v1.6.3 A-P1-01(audit):参考徽章语法 = 淡彩底+彩字(tinted),不再实底#ef4444+白字
        destructive: "bg-red-50 text-red-600",
        // v1.6.3 A-P1-02(audit):中间态/待分类 = 琥珀淡底+琥珀字(与详情页待分类统一同一 token)
        warning: "bg-amber-50 text-amber-600",
        // v1.6.3 A-P2-02(audit):「不完整」蓝系徽章(信息/中间态语义)
        info: "bg-blue-50 text-blue-600",
        outline: "border border-input",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}
