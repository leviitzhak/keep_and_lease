import { integer, sqliteTable, text } from "drizzle-orm/sqlite-core";

export const strategyParameters = sqliteTable("strategy_parameters", {
  userId: text("user_id").primaryKey(),
  parametersJson: text("parameters_json").notNull(),
  updatedAt: integer("updated_at").notNull(),
});
