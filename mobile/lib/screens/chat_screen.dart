import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/errors.dart';
import '../core/theme.dart';
import '../models/models.dart';
import '../services/api_client.dart';
import '../state/studio_store.dart';
import '../widgets/common.dart';

/// Chat workspace — real streaming generation against `/api/chat`.
///
/// Only models that pass the backend's hard "chat" gate are selectable; if none
/// qualify the screen says so instead of offering an unusable model.
class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final List<ChatTurn> _turns = [];
  String? _conversationId;
  String _model = '';
  bool _sending = false;

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty || _sending) return;
    final store = context.read<StudioStore>();
    final api = context.read<AsafApi>();

    setState(() {
      _turns.add(ChatTurn(role: 'user', content: text));
      _sending = true;
      _input.clear();
    });
    _scrollToEnd();

    final projectId = await store.ensureActiveProject();
    if (projectId == null) {
      setState(() {
        _turns.add(ChatTurn(role: 'assistant', content: '', error: 'No project available — the backend did not return one.'));
        _sending = false;
      });
      return;
    }

    final assistant = ChatTurn(role: 'assistant', content: '', pending: true, model: _model);
    setState(() => _turns.add(assistant));
    _scrollToEnd();

    final history = _turns
        .where((t) => !t.pending && t.error.isEmpty && t.content.isNotEmpty)
        .map((t) => {'role': t.role, 'content': t.content})
        .toList();

    try {
      await for (final event in api.chatStream(
        message: text,
        projectId: projectId,
        conversationId: _conversationId,
        model: _model,
        history: history,
      )) {
        final type = event['type']?.toString();
        if (type == 'token') {
          setState(() {
            assistant.pending = false;
            assistant.content += event['text']?.toString() ?? '';
          });
          _scrollToEnd();
        } else if (type == 'error') {
          setState(() {
            assistant.pending = false;
            assistant.error = event['error']?.toString() ?? 'Generation failed.';
          });
        } else if (type == 'done') {
          _conversationId ??= event['conversation_id']?.toString();
          final usedModel = event['model']?.toString();
          setState(() {
            assistant.pending = false;
            if (assistant.content.isEmpty && assistant.error.isEmpty) {
              assistant.content = '(the model returned an empty response)';
            }
            if (usedModel != null && usedModel.isNotEmpty && _model.isEmpty) {
              assistant.model = usedModel;
            }
          });
        }
      }
    } on ApiException catch (e) {
      setState(() {
        assistant.pending = false;
        assistant.error = e.message;
      });
    } catch (e) {
      setState(() {
        assistant.pending = false;
        assistant.error = 'Generation failed: $e';
      });
    } finally {
      if (mounted) setState(() => _sending = false);
      _scrollToEnd();
    }
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(_scroll.position.maxScrollExtent + 120, duration: const Duration(milliseconds: 220), curve: Curves.easeOut);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final store = context.watch<StudioStore>();
    final models = store.chatModels;

    return Column(
      children: [
        _header(models),
        const Divider(height: 1),
        Expanded(
          child: _turns.isEmpty
              ? EmptyState(
                  icon: Icons.chat_bubble_outline,
                  title: 'Start a conversation',
                  message: models.isEmpty
                      ? 'No chat-capable model is AVAILABLE on the backend. Configure a provider to enable chat.'
                      : 'Ask anything. Generation streams live from your ASAF AI backend.',
                )
              : ListView.builder(
                  controller: _scroll,
                  padding: const EdgeInsets.all(16),
                  itemCount: _turns.length,
                  itemBuilder: (_, i) => _bubble(_turns[i]),
                ),
        ),
        _composer(models.isNotEmpty),
      ],
    );
  }

  Widget _header(List<ModelEntry> models) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      color: AsafColors.surface,
      child: Row(
        children: [
          const Icon(Icons.forum, size: 18, color: AsafColors.primaryLight),
          const SizedBox(width: 8),
          const Text('Chat', style: AsafText.h3),
          const Spacer(),
          if (models.isEmpty)
            const StatusBadge('UNAVAILABLE', dense: true)
          else
            Flexible(
              child: DropdownButtonHideUnderline(
                child: DropdownButton<String>(
                  value: _model.isEmpty ? null : _model,
                  isDense: true,
                  dropdownColor: AsafColors.surfaceHigh,
                  hint: const Text('Auto-route', style: AsafText.small),
                  items: [
                    const DropdownMenuItem(value: '', child: Text('Auto-route', style: AsafText.small)),
                    ...models.map((m) => DropdownMenuItem(
                          value: m.id,
                          child: Text(m.id, style: AsafText.small.copyWith(color: AsafColors.textPrimary)),
                        )),
                  ],
                  onChanged: (v) => setState(() => _model = v ?? ''),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _bubble(ChatTurn t) {
    final isUser = t.role == 'user';
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 560),
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: isUser ? AsafColors.primary.withValues(alpha: 0.18) : AsafColors.surface,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: isUser ? AsafColors.primary.withValues(alpha: 0.5) : AsafColors.border),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(isUser ? Icons.person : Icons.auto_awesome, size: 14, color: AsafColors.textMuted),
                const SizedBox(width: 6),
                Text(isUser ? 'You' : 'ASAF AI', style: AsafText.small.copyWith(fontWeight: FontWeight.w600)),
                if (!isUser && t.model.isNotEmpty) ...[
                  const SizedBox(width: 8),
                  Flexible(child: Text(t.model, style: AsafText.small, overflow: TextOverflow.ellipsis)),
                ],
              ],
            ),
            const SizedBox(height: 8),
            if (t.pending && t.content.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 4),
                child: SizedBox(height: 16, width: 16, child: CircularProgressIndicator(strokeWidth: 2)),
              )
            else if (t.error.isNotEmpty)
              Text(t.error, style: AsafText.body.copyWith(color: AsafColors.statusError))
            else
              SelectableText(t.content, style: AsafText.body.copyWith(color: AsafColors.textPrimary)),
          ],
        ),
      ),
    );
  }

  Widget _composer(bool hasModels) {
    return Container(
      padding: EdgeInsets.only(left: 12, right: 12, top: 10, bottom: 10 + MediaQuery.of(context).padding.bottom),
      decoration: const BoxDecoration(
        color: AsafColors.surface,
        border: Border(top: BorderSide(color: AsafColors.border)),
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _input,
              minLines: 1,
              maxLines: 5,
              enabled: hasModels && !_sending,
              decoration: InputDecoration(
                hintText: hasModels ? 'Message ASAF AI…' : 'Chat unavailable — no model is AVAILABLE',
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(24)),
                contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              ),
              onSubmitted: (_) => _send(),
            ),
          ),
          const SizedBox(width: 8),
          IconButton.filled(
            onPressed: hasModels && !_sending ? _send : null,
            icon: _sending
                ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.send),
          ),
        ],
      ),
    );
  }
}
