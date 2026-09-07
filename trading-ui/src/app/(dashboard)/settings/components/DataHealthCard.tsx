"use client"

import React, { useCallback, useEffect, useState } from "react"
import { Activity, RefreshCw, ShieldCheck, ShieldAlert, HelpCircle } from "lucide-react"
import { toast } from "sonner"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { fetchClient } from "@/lib/api/client"
import { useLanguage } from "@/contexts/language-context"

const SOURCE_LABELS: Record<string, string> = {
  dnse: "DNSE Entrade (OHLCV)",
  "vnstock-vci": "vnstock / VCI (OHLCV + cơ bản)",
  tcbs: "TCBS (OHLCV)",
}

interface SourceHealth {
  attempts: number
  successes: number
  last_ok: boolean | null
  last_attempt_ts?: number
  last_success_ts?: number
  last_error?: string
  recent_success_rate: number | null
}

export const DataHealthCard: React.FC = () => {
  const { t } = useLanguage()
  const [sources, setSources] = useState<Record<string, SourceHealth>>({})
  const [learning, setLearning] = useState<any>(null)
  const [isProbing, setIsProbing] = useState(false)
  const [hasData, setHasData] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await fetchClient("/system/data-health")
      setSources(data.sources || {})
      setLearning(data.learning || null)
      setHasData(Object.keys(data.sources || {}).length > 0)
    } catch {
      // im lặng: card này chỉ là diagnostic, không cần toast lỗi khi load
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const probe = async () => {
    setIsProbing(true)
    try {
      await fetchClient("/system/data-health/probe", { method: "POST" })
      await load()
      toast.success(t("settings.dataHealth.probeSuccess"))
    } catch {
      // user chủ động bấm nút nên phải có feedback, kể cả lỗi
      toast.error(t("settings.dataHealth.probeError"))
    } finally {
      setIsProbing(false)
    }
  }

  const learningN = learning?.total_n ?? 0

  return (
    <Card className="shadow-sm rounded-2xl bg-card/40 backdrop-blur">
      <CardHeader className="bg-muted/30 pb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between space-y-0">
        <div className="flex items-center gap-2 min-w-0">
          <Activity className="h-5 w-5 text-primary shrink-0" />
          <div className="min-w-0">
            <CardTitle className="text-base">{t("settings.dataHealth.title")}</CardTitle>
            <CardDescription className="text-xs">
              {t("settings.dataHealth.description")}
            </CardDescription>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-xs border-primary/20 hover:border-primary/50 shrink-0 self-start sm:self-auto"
          onClick={probe}
          disabled={isProbing}
        >
          <RefreshCw className={`h-3.5 w-3.5 mr-1 ${isProbing ? "animate-spin motion-reduce:animate-none" : ""}`} />
          {t("settings.dataHealth.probe")}
        </Button>
      </CardHeader>
      <CardContent className="p-6 space-y-5">
        {!hasData && (
          <p className="text-xs text-muted-foreground">
            {t("settings.dataHealth.empty")}
          </p>
        )}
        <div className="space-y-3">
          {Object.entries(sources).map(([key, s]) => (
            <div
              key={key}
              className="flex items-center justify-between rounded-xl border border-border/40 bg-background/30 px-4 py-3"
            >
              <div className="flex items-center gap-3 min-w-0">
                {s.last_ok === true ? (
                  <ShieldCheck className="h-4 w-4 text-green-500 shrink-0" />
                ) : s.last_ok === false ? (
                  <ShieldAlert className="h-4 w-4 text-red-500 shrink-0" />
                ) : (
                  <HelpCircle className="h-4 w-4 text-muted-foreground shrink-0" />
                )}
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{SOURCE_LABELS[key] || key}</p>
                  {s.last_error && (
                    <p className="text-[11px] text-muted-foreground truncate max-w-[420px]">
                      {s.last_error}
                    </p>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {s.recent_success_rate !== null && (
                  <Badge
                    variant="secondary"
                    className={
                      s.recent_success_rate >= 70
                        ? "bg-green-500/10 text-green-400 border-green-500/20"
                        : s.recent_success_rate >= 40
                        ? "bg-yellow-500/10 text-yellow-400 border-yellow-500/20"
                        : "bg-red-500/10 text-red-400 border-red-500/20"
                    }
                  >
                    {s.recent_success_rate}% ok
                  </Badge>
                )}
                <span className="text-[11px] text-muted-foreground w-16 text-right">
                  {s.successes}/{s.attempts}
                </span>
              </div>
            </div>
          ))}
        </div>
        {learningN > 0 && (
          <div className="flex items-center justify-between rounded-xl border border-primary/20 bg-primary/5 px-4 py-3">
            <div className="min-w-0">
              <p className="text-sm font-medium">{t("settings.dataHealth.learning")}</p>
              <p className="text-[11px] text-muted-foreground">
                {learningN} {t("settings.dataHealth.learningDetail")}
                {learning?.overall_hit_rate != null && ` — hit-rate ${Math.round(learning.overall_hit_rate * 100)}%`}
              </p>
            </div>
            {learning?.signal_ic != null && (
              <Badge variant="secondary" className="bg-primary/10 text-primary border-primary/20 shrink-0">
                IC {learning.signal_ic > 0 ? "+" : ""}{learning.signal_ic}
              </Badge>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
