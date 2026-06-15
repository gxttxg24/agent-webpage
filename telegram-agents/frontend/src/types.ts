export type Message = {
  id: string;
  role: "user" | "assistant" | "system" | "bot";
  text: string;
  createdAt: Date;
  senderName?: string;
  username?: string;
};

export type ServerEvent = {
  type: string;
  text?: string;
  label?: string;
  active?: boolean;
  days?: ScheduleDay[];
  owner_profile?: string;
  bots?: BotParticipant[];
  bot?: BotParticipant;
  username?: string;
  reason?: string;
  already_invited?: boolean;
  message?: GroupMessageEvent;
};

export type GroupMessageEvent = {
  sender: "bot";
  sender_profile: string;
  sender_name: string;
  username: string;
  text: string;
};

export type BotParticipant = {
  profile: string;
  username: string;
  display_name: string;
  role: string;
  invited: boolean;
};

export type ScheduleEvent = {
  id: number;
  title: string;
  starts_at: string;
  ends_at: string;
  start_time: string;
  end_time: string;
  duration_minutes: number;
};

export type ScheduleDay = {
  date: string;
  weekday: string;
  events: ScheduleEvent[];
};

export type ActiveView = "group" | "schedule" | "private";
