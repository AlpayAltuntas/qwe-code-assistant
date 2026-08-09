CREATE TABLE "tool_invocations" (
	"id" serial PRIMARY KEY NOT NULL,
	"tool" text NOT NULL,
	"format" text NOT NULL,
	"verdict" text,
	"summary" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
