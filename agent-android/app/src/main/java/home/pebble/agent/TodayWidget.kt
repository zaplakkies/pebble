package home.pebble.agent

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews

/** Home-screen widget with today's time. Refreshed after every agent run. */
class TodayWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        render(context, manager, ids)
    }

    companion object {
        fun refresh(context: Context) {
            val manager = AppWidgetManager.getInstance(context)
            val ids = manager.getAppWidgetIds(ComponentName(context, TodayWidget::class.java))
            if (ids.isNotEmpty()) render(context, manager, ids)
        }

        private fun render(context: Context, manager: AppWidgetManager, ids: IntArray) {
            val views = RemoteViews(context.packageName, R.layout.widget_today)
            if (Prefs(context).paired) {
                val t = Agent.today(context)
                views.setTextViewText(R.id.widget_used, Today.formatDuration(t.usedS))
                views.setTextViewText(R.id.widget_limit, describeLimit(context, t))
            } else {
                views.setTextViewText(R.id.widget_used, "–")
                views.setTextViewText(R.id.widget_limit, context.getString(R.string.not_set_up))
            }
            val open = PendingIntent.getActivity(context, 0, Intent(context, MainActivity::class.java),
                PendingIntent.FLAG_IMMUTABLE)
            views.setOnClickPendingIntent(R.id.widget_root, open)
            manager.updateAppWidget(ids, views)
        }

        fun describeLimit(context: Context, t: TodayStatus): String {
            val limit = t.limitS ?: return context.getString(R.string.today_no_limit)
            val left = limit - t.usedS
            return if (left > 0) context.getString(R.string.today_left, Today.formatDuration(left),
                Today.formatDuration(limit))
            else context.getString(R.string.today_over, Today.formatDuration(-left), Today.formatDuration(limit))
        }
    }
}
