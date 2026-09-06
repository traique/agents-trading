"use client"

import React, { useState } from "react"
import {
  Bot,
  Brain,
  Coins,
  Cpu,
  LineChart,
  Play,
  ShieldCheck,
  Users,
  ChevronRight,
  Sparkles,
  Database,
  Activity,
  TrendingUp,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import Link from "next/link"
import { useLanguage } from "@/contexts/language-context"
import { useAuthStore } from "@/store/authStore"

const WORKFLOW_STEPS = [
  {
    id: "data",
    icon: Database,
    color: "from-blue-500 to-cyan-500 animate-pulse",
  },
  {
    id: "analysts",
    icon: Users,
    color: "from-cyan-500 to-teal-500",
    subAgents: ["Fundamentals Analyst", "Sentiment Analyst", "News Analyst", "Technical Analyst"],
  },
  {
    id: "researchers",
    icon: Brain,
    color: "from-purple-500 to-pink-500",
    subAgents: ["Bull Researcher", "Bear Researcher", "Research Manager"],
  },
  {
    id: "risk",
    icon: ShieldCheck,
    color: "from-orange-500 to-red-500",
    subAgents: ["Trader Agent", "Risk Management", "Portfolio Manager"],
  },
  {
    id: "exchange",
    icon: Coins,
    color: "from-green-500 to-emerald-500",
  },
]

const TEAM_CARDS = [
  {
    href: "teamAnalyst",
    icon: LineChart,
    tint: "text-cyan-600 dark:text-cyan-400",
    ring: "bg-cyan-500/10 border-cyan-500/20",
  },
  {
    href: "teamResearch",
    icon: Brain,
    tint: "text-purple-600 dark:text-purple-400",
    ring: "bg-purple-500/10 border-purple-500/20",
  },
  {
    href: "teamTrader",
    icon: Bot,
    tint: "text-orange-600 dark:text-orange-400",
    ring: "bg-orange-500/10 border-orange-500/20",
  },
  {
    href: "teamPortfolio",
    icon: ShieldCheck,
    tint: "text-emerald-600 dark:text-emerald-400",
    ring: "bg-emerald-500/10 border-emerald-500/20",
  },
]

function getInitials(email: string): string {
  const parts = email.split("@")[0].split(/[._-]/)
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase()
  }
  return email.substring(0, 2).toUpperCase()
}

function getGreeting(): string {
  const hour = new Date().getHours()
  if (hour < 12) return "Chào buổi sáng"
  if (hour < 18) return "Chào buổi chiều"
  return "Chào buổi tối"
}

export default function HomeIntroPage() {
  const [activeStep, setActiveStep] = useState<string>("data")
  const { t } = useLanguage()
  const { user } = useAuthStore()

  const displayName = user?.email?.split("@")[0] ?? "Trader"
  const initials = user?.email ? getInitials(user.email) : "T"
  const greeting = getGreeting()

  const current = WORKFLOW_STEPS.find((s) => s.id === activeStep) ?? WORKFLOW_STEPS[0]
  const CurrentIcon = current.icon

  return (
    <div className="h-full w-full overflow-y-auto custom-scrollbar p-6">
      <div className="mx-auto w-full max-w-6xl pb-12 space-y-6">
        <div className="bento">
          {/* Hero */}
          <div className="bento-2 glass p-7 relative overflow-hidden">
            <div className="absolute -top-16 -right-16 w-64 h-64 bg-primary/15 rounded-full blur-[100px] pointer-events-none" />
            <div className="relative flex h-full flex-col justify-between gap-6">
              <div className="flex items-center gap-4">
                <div className="relative">
                  <div className="flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-primary to-cyan-600 text-sm font-black text-white shadow-lg">
                    {initials}
                  </div>
                  <span className="absolute bottom-0 right-0 h-3 w-3 rounded-full border-2 border-white bg-emerald-400 dark:border-[#1a1a22]" />
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">{greeting},</p>
                  <h2 className="text-lg font-semibold capitalize tracking-tight">{displayName}</h2>
                </div>
                <div className="ml-auto hidden items-center gap-2 md:flex">
                  <span className="flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                    <Activity className="h-3 w-3 animate-pulse" /> Online
                  </span>
                  <span className="flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
                    <TrendingUp className="h-3 w-3" /> AI Ready
                  </span>
                </div>
              </div>

              <div className="space-y-4">
                <Badge variant="outline" className="border-primary/30 bg-primary/5 px-3 py-1 text-primary">
                  <Sparkles className="mr-1.5 h-3.5 w-3.5" /> {t("home.badge")}
                </Badge>
                <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
                  {t("home.title")}
                </h1>
                <p className="max-w-xl leading-relaxed text-muted-foreground">
                  {t("home.description")}
                </p>
                <div className="flex flex-wrap gap-3 pt-1">
                  <Button asChild size="lg" className="rounded-full px-6 shadow-lg shadow-primary/25">
                    <Link href="/research" className="flex items-center gap-2">
                      <Play className="h-4 w-4 fill-current" /> {t("home.runSim")}
                    </Link>
                  </Button>
                  <Button asChild size="lg" variant="outline" className="rounded-full px-6">
                    <Link href="/jobs" className="flex items-center gap-2">
                      {t("home.manageSchedules")}
                    </Link>
                  </Button>
                </div>
              </div>
            </div>
          </div>

          {/* Workflow */}
          <div className="bento-2 bento-tall glass p-7 flex flex-col">
            <div>
              <h3 className="text-lg font-semibold tracking-tight">{t("home.workflowTitle")}</h3>
              <p className="text-sm text-muted-foreground">{t("home.workflowDesc")}</p>
            </div>

            <div className="mt-6 flex flex-1 flex-col items-center justify-between gap-3">
              <div className="flex w-full flex-col items-center gap-3 md:flex-row md:justify-between md:gap-1">
                {WORKFLOW_STEPS.map((step, idx) => {
                  const Icon = step.icon
                  const isActive = activeStep === step.id
                  return (
                    <React.Fragment key={step.id}>
                      {idx > 0 && (
                        <div className="hidden h-px flex-1 bg-gradient-to-r from-border to-primary/40 md:block" />
                      )}
                      <button
                        onClick={() => setActiveStep(step.id)}
                        className={`flex w-24 flex-col items-center gap-2 rounded-2xl border p-3 transition-all duration-300 ${
                          isActive
                            ? "border-primary/50 bg-primary/10 shadow-lg shadow-primary/10 scale-105"
                            : "border-transparent bg-muted/30 hover:bg-muted/50"
                        }`}
                      >
                        <div className={`rounded-xl bg-gradient-to-br ${step.color} p-2 text-white shadow-md`}>
                          <Icon className="h-4 w-4" />
                        </div>
                        <span className="text-[11px] font-medium leading-tight">
                          {t(`home.step.${step.id}.label` as any)}
                        </span>
                      </button>
                    </React.Fragment>
                  )
                })}
              </div>

              <div className="w-full rounded-2xl border border-border/60 bg-background/40 p-5 min-h-[150px] flex flex-col justify-between">
                <div>
                  <div className="mb-2 flex items-center gap-2">
                    <CurrentIcon className="h-5 w-5 text-primary" />
                    <h4 className="font-semibold">{t(`home.step.${current.id}.label` as any)}</h4>
                  </div>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    {t(`home.step.${current.id}.desc` as any)}
                  </p>
                </div>
                {current.subAgents && (
                  <div className="mt-4 border-t border-border/40 pt-3">
                    <div className="mb-2 text-[10px] uppercase tracking-wider text-muted-foreground">
                      {t("home.activeAgents")}
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {current.subAgents.map((sa) => (
                        <Badge
                          key={sa}
                          variant="outline"
                          className="bg-primary/5 border-primary/20 px-2 py-0.5 text-xs text-primary"
                        >
                          {sa}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Tech stack */}
          <div className="glass p-6 flex flex-col justify-between">
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <Cpu className="h-5 w-5 text-cyan-600 dark:text-cyan-400" />
                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  {t("home.techTitle")}
                </h3>
              </div>
              <div className="space-y-3">
                <div className="rounded-xl bg-muted/40 p-3.5">
                  <h4 className="mb-1 text-xs font-semibold">{t("home.techState")}</h4>
                  <p className="text-[11px] leading-relaxed text-muted-foreground">
                    {t("home.techStateDesc")}
                  </p>
                </div>
                <div className="rounded-xl bg-muted/40 p-3.5">
                  <h4 className="mb-1 text-xs font-semibold">{t("home.techMemory")}</h4>
                  <p className="text-[11px] leading-relaxed text-muted-foreground">
                    {t("home.techMemoryDesc")}
                  </p>
                </div>
              </div>
            </div>
            <Link
              href="/research"
              className="mt-4 flex items-center gap-1 border-t border-border/40 pt-3 text-xs text-primary hover:underline"
            >
              {t("home.goConsole")} <ChevronRight className="h-3 w-3" />
            </Link>
          </div>

          {/* Team cards - 4 ô nhỏ hàng dưới */}
          {TEAM_CARDS.map((card) => {
            const Icon = card.icon
            return (
              <div key={card.href} className="glass p-5 flex flex-col gap-3 transition-transform hover:-translate-y-0.5">
                <div className={`flex h-10 w-10 items-center justify-center rounded-xl border ${card.ring}`}>
                  <Icon className={`h-5 w-5 ${card.tint}`} />
                </div>
                <h3 className="text-sm font-semibold">{t(`home.${card.href}Title` as any)}</h3>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {t(`home.${card.href}Desc` as any)}
                </p>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
