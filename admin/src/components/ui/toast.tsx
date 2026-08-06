import { Toaster as Sonner } from "sonner";
import { cn } from "@/lib/utils";

function Toaster({ className }: { className?: string }) {
  return (
    <Sonner
      className={cn(className)}
      toastOptions={{
        classNames: {
          toast:
            "group border bg-card text-card-foreground shadow-lg rounded-lg",
          title: "text-sm font-semibold",
          description: "text-sm text-muted-foreground",
          actionButton: "bg-primary text-primary-foreground",
          cancelButton: "bg-muted text-muted-foreground",
        },
      }}
    />
  );
}

export { Toaster };
