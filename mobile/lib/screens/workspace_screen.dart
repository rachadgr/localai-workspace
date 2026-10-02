import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/errors.dart';
import '../core/theme.dart';
import '../models/models.dart';
import '../state/studio_store.dart';
import '../widgets/common.dart';

/// Project Workspace — the per-project view of everything the backend really
/// stored: conversations, artifacts (documents/slides/files), uploaded files and
/// the generation history. It reuses the existing project/document/artifact APIs
/// (`/api/workspace/{id}`) and never duplicates or fabricates records.
class WorkspaceScreen extends StatefulWidget {
  const WorkspaceScreen({super.key});

  @override
  State<WorkspaceScreen> createState() => _WorkspaceScreenState();
}

class _WorkspaceScreenState extends State<WorkspaceScreen> {
  Map<String, dynamic>? _data;
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final store = context.read<StudioStore>();
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final projectId = await store.ensureActiveProject();
      if (projectId == null) {
        setState(() {
          _error = 'No active project — the backend did not return one.';
          _loading = false;
        });
        return;
      }
      final data = await store.workspace(projectId);
      setState(() {
        _data = data;
        _loading = false;
      });
    } on ApiException catch (e) {
      setState(() {
        _error = e.message;
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _error = 'Workspace failed to load: $e';
        _loading = false;
      });
    }
  }

  Future<void> _createProject() async {
    final store = context.read<StudioStore>();
    await store.loadProjects();
    if (mounted) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final store = context.watch<StudioStore>();
    final project = (_data?['project'] as Map?)?.cast<String, dynamic>();

    return Column(
      children: [
        Container(
          color: AsafColors.surface,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          child: Row(
            children: [
              const Icon(Icons.folder_copy, size: 18, color: AsafColors.primaryLight),
              const SizedBox(width: 8),
              const Text('Project Workspace', style: AsafText.h3),
              const Spacer(),
              if (store.projects.isNotEmpty)
                Flexible(
                  child: DropdownButtonHideUnderline(
                    child: DropdownButton<String>(
                      value: store.activeProjectId,
                      isDense: true,
                      dropdownColor: AsafColors.surfaceHigh,
                      items: store.projects
                          .map((p) => DropdownMenuItem(
                                value: p['id']?.toString(),
                                child: Text(
                                  p['name']?.toString() ?? 'project',
                                  style: AsafText.small.copyWith(color: AsafColors.textPrimary),
                                ),
                              ))
                          .toList(),
                      onChanged: (v) async {
                        if (v == null) return;
                        store.activeProjectId = v;
                        await _load();
                      },
                    ),
                  ),
                ),
              IconButton(onPressed: _load, icon: const Icon(Icons.refresh, size: 20), tooltip: 'Refresh'),
            ],
          ),
        ),
        const Divider(height: 1),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _error != null
                  ? EmptyState(icon: Icons.error_outline, title: 'Cannot load workspace', message: _error, onRetry: _load)
                  : _body(project),
        ),
      ],
    );
  }

  Widget _body(Map<String, dynamic>? project) {
    if (_data == null) {
      return EmptyState(
        icon: Icons.folder_open,
        title: 'No workspace yet',
        message: 'Create a project to store conversations, documents and generations.',
        onRetry: _createProject,
        retryLabel: 'Create / load project',
      );
    }
    final conversations = ((_data!['conversations'] as List?) ?? []).map((e) => (e as Map).cast<String, dynamic>()).toList();
    final documents = ((_data!['documents'] as List?) ?? []).map((e) => (e as Map).cast<String, dynamic>()).toList();
    final slides = ((_data!['slides'] as List?) ?? []).map((e) => (e as Map).cast<String, dynamic>()).toList();
    final files = ((_data!['files'] as List?) ?? []).map((e) => (e as Map).cast<String, dynamic>()).toList();
    final generations = ((_data!['generations'] as List?) ?? []).map((e) => (e as Map).cast<String, dynamic>()).toList();

    return RefreshIndicator(
      color: AsafColors.primary,
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          SectionCard(
            title: project?['name']?.toString() ?? 'Project',
            icon: Icons.folder_special,
            action: StatusBadge(project?['status']?.toString().toUpperCase() ?? 'ACTIVE', dense: true),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if ((project?['description']?.toString() ?? '').isNotEmpty)
                  Text(project!['description'].toString(), style: AsafText.body),
                const SizedBox(height: 10),
                KeyValue('Project id', project?['id']?.toString() ?? ''),
                KeyValue('Updated', project?['updated_at']?.toString() ?? ''),
                KeyValue('Conversations', '${conversations.length}'),
                KeyValue('Documents', '${documents.length}'),
                KeyValue('Slide decks', '${slides.length}'),
                KeyValue('Files', '${files.length}'),
                KeyValue('Generations', '${generations.length}'),
              ],
            ),
          ),
          const SizedBox(height: 16),
          _artifactSection('Documents', Icons.description_outlined, documents, 'No documents yet.'),
          const SizedBox(height: 16),
          _artifactSection('Slide decks', Icons.slideshow_outlined, slides, 'No slide decks yet.'),
          const SizedBox(height: 16),
          _conversationSection(conversations),
          const SizedBox(height: 16),
          _fileSection(files),
          const SizedBox(height: 16),
          _generationSection(generations),
        ],
      ),
    );
  }

  Widget _artifactSection(String title, IconData icon, List<Map<String, dynamic>> items, String empty) {
    return SectionCard(
      title: title,
      icon: icon,
      child: items.isEmpty
          ? Text(empty, style: AsafText.body)
          : Column(
              children: items.map((a) {
                final ref = ArtifactRef.fromJson(a);
                return ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(icon, size: 18, color: AsafColors.primaryLight),
                  title: Text(ref.name, style: AsafText.body.copyWith(color: AsafColors.textPrimary), maxLines: 1, overflow: TextOverflow.ellipsis),
                  subtitle: Text('${ref.mimeType} · ${ref.sizeLabel}', style: AsafText.small, maxLines: 1, overflow: TextOverflow.ellipsis),
                  trailing: StatusBadge('AVAILABLE', dense: true),
                );
              }).toList(),
            ),
    );
  }

  Widget _conversationSection(List<Map<String, dynamic>> conversations) {
    return SectionCard(
      title: 'Conversations',
      icon: Icons.forum_outlined,
      child: conversations.isEmpty
          ? const Text('No conversations yet.', style: AsafText.body)
          : Column(
              children: conversations.map((c) {
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(
                    children: [
                      const Icon(Icons.chat_bubble_outline, size: 17, color: AsafColors.primaryLight),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(c['title']?.toString() ?? '', style: AsafText.body.copyWith(color: AsafColors.textPrimary), maxLines: 1, overflow: TextOverflow.ellipsis),
                            Text('${c['mode'] ?? ''} · ${c['updated_at'] ?? ''}', style: AsafText.small, maxLines: 1, overflow: TextOverflow.ellipsis),
                          ],
                        ),
                      ),
                    ],
                  ),
                );
              }).toList(),
            ),
    );
  }

  Widget _fileSection(List<Map<String, dynamic>> files) {
    return SectionCard(
      title: 'Uploaded files',
      icon: Icons.attach_file,
      child: files.isEmpty
          ? const Text('No files uploaded yet.', style: AsafText.body)
          : Column(
              children: files.map((f) {
                final size = (f['size'] as num?)?.toInt() ?? 0;
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(
                    children: [
                      const Icon(Icons.insert_drive_file_outlined, size: 17, color: AsafColors.primaryLight),
                      const SizedBox(width: 10),
                      Expanded(child: Text(f['name']?.toString() ?? '', style: AsafText.body.copyWith(color: AsafColors.textPrimary), maxLines: 1, overflow: TextOverflow.ellipsis)),
                      Text('${f['category'] ?? ''} · ${size}B', style: AsafText.small),
                    ],
                  ),
                );
              }).toList(),
            ),
    );
  }

  Widget _generationSection(List<Map<String, dynamic>> generations) {
    return SectionCard(
      title: 'Generations',
      icon: Icons.history,
      child: generations.isEmpty
          ? const Text('No generations yet.', style: AsafText.body)
          : Column(
              children: generations.take(20).map((g) {
                final t = HistoryTask.fromJson(g);
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(t.title.isEmpty ? t.kind : t.title, style: AsafText.body.copyWith(color: AsafColors.textPrimary), maxLines: 1, overflow: TextOverflow.ellipsis),
                            Text('${t.kind} · ${t.modelLabel} · ${t.when}', style: AsafText.small, maxLines: 1, overflow: TextOverflow.ellipsis),
                          ],
                        ),
                      ),
                      StatusBadge(t.status, dense: true),
                    ],
                  ),
                );
              }).toList(),
            ),
    );
  }
}
