import 'package:flutter/material.dart';

class HomePage extends StatelessWidget {
  const HomePage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Column(
        children: [
          Text('Projects'),
          ElevatedButton(onPressed: () {}, child: Text('Create project')),
        ],
      ),
    );
  }
}
