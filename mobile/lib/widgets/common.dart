import 'package:flutter/material.dart';

import '../core/theme.dart';

/// Small coloured badge for a backend status string (AVAILABLE / NOT_CONFIGURED
/// / UNAVAILABLE / …). The colour vocabulary matches the design system exactly.
class StatusBadge extends StatelessWidget {
  const StatusBadge(this.status, {super.key, this.dense = false});

  final String status;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final color = AsafColors.forStatus(status);
    return Container(
      padding: EdgeInsets.symmetric(horizontal: dense ? 8 : 10, vertical: dense ? 3 : 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: 0.5)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(width: 7, height: 7, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
          const SizedBox(width: 6),
          Text(
            status.replaceAll('_', ' '),
            style: TextStyle(color: color, fontSize: dense ? 10.5 : 11.5, fontWeight: FontWeight.w600, letterSpacing: 0.3),
          ),
        ],
      ),
    );
  }
}

/// A titled panel used across every screen for visual consistency.
class SectionCard extends StatelessWidget {
  const SectionCard({super.key, required this.title, this.action, required this.child, this.icon});

  final String title;
  final Widget? action;
  final Widget child;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                if (icon != null) ...[
                  Icon(icon, size: 18, color: AsafColors.primaryLight),
                  const SizedBox(width: 8),
                ],
                Expanded(child: Text(title, style: AsafText.h3)),
                if (action != null) action!,
              ],
            ),
            const SizedBox(height: 14),
            child,
          ],
        ),
      ),
    );
  }
}

/// Centered empty / error / info state with an optional retry.
class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.icon, required this.title, this.message, this.onRetry, this.retryLabel = 'Retry'});

  final IconData icon;
  final String title;
  final String? message;
  final VoidCallback? onRetry;
  final String retryLabel;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 44, color: AsafColors.textMuted),
            const SizedBox(height: 14),
            Text(title, style: AsafText.h3, textAlign: TextAlign.center),
            if (message != null) ...[
              const SizedBox(height: 8),
              Text(message!, style: AsafText.body, textAlign: TextAlign.center),
            ],
            if (onRetry != null) ...[
              const SizedBox(height: 16),
              OutlinedButton.icon(onPressed: onRetry, icon: const Icon(Icons.refresh, size: 18), label: Text(retryLabel)),
            ],
          ],
        ),
      ),
    );
  }
}

/// Label/value row.
class KeyValue extends StatelessWidget {
  const KeyValue(this.label, this.value, {super.key, this.valueColor});

  final String label;
  final String value;
  final Color? valueColor;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 132, child: Text(label, style: AsafText.small)),
          Expanded(
            child: Text(
              value.isEmpty ? '—' : value,
              style: AsafText.body.copyWith(color: valueColor ?? AsafColors.textPrimary, fontWeight: FontWeight.w500),
            ),
          ),
        ],
      ),
    );
  }
}

/// Small pill for capability / category tags.
class Tag extends StatelessWidget {
  const Tag(this.text, {super.key, this.color});
  final String text;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final c = color ?? AsafColors.accentAlt;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      margin: const EdgeInsets.only(right: 6, bottom: 6),
      decoration: BoxDecoration(
        color: c.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: c.withValues(alpha: 0.35)),
      ),
      child: Text(text, style: TextStyle(color: c, fontSize: 11, fontWeight: FontWeight.w500)),
    );
  }
}

/// Inline banner for errors / warnings that are not full-screen.
class InfoBanner extends StatelessWidget {
  const InfoBanner({super.key, required this.message, this.color, this.icon = Icons.info_outline});

  final String message;
  final Color? color;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final c = color ?? AsafColors.primaryLight;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: c.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: c.withValues(alpha: 0.35)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 18, color: c),
          const SizedBox(width: 10),
          Expanded(child: Text(message, style: AsafText.body.copyWith(color: AsafColors.textPrimary))),
        ],
      ),
    );
  }
}
