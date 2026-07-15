"use client";

import { useQuery } from "@tanstack/react-query";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getHealth, type ServiceState } from "@/lib/api";
import { cn } from "@/lib/utils";

function ServiceRow({ name, state }: { name: string; state: ServiceState | undefined }) {
  return (
    <div className="flex items-center justify-between py-1">
      <span>{name}</span>
      <span
        className={cn(
          "font-medium",
          state === "healthy" && "text-success",
          state === "unreachable" && "text-destructive",
          state === undefined && "text-muted-foreground",
        )}
      >
        {state ?? "checking…"}
      </span>
    </div>
  );
}

export function HealthStatus() {
  const { data, isError } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 5000,
  });

  return (
    <Card data-testid="health-status">
      <CardHeader>
        <CardTitle>System health</CardTitle>
        <CardDescription>
          {isError
            ? "API unreachable"
            : data
              ? data.status === "ok"
                ? "All services healthy"
                : "Degraded"
              : "Checking…"}
        </CardDescription>
      </CardHeader>
      <CardContent className="text-sm">
        <ServiceRow name="Database" state={isError ? "unreachable" : data?.db} />
        <ServiceRow name="Redis" state={isError ? "unreachable" : data?.redis} />
      </CardContent>
    </Card>
  );
}
