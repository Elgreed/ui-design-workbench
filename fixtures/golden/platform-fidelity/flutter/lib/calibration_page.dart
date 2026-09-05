import 'package:flutter/material.dart';

class CalibrationPage extends StatelessWidget {
  const CalibrationPage({super.key});

  @override
  Widget build(BuildContext context) => Container(
    width: 400, height: 360, color: const Color(0xFFF5F5F5),
    padding: const EdgeInsets.fromLTRB(24, 16, 40, 32),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Platform sample', style: TextStyle(fontFamily: 'Arial', fontSize: 20, height: 1.4, color: Color(0xFF123456))),
        const SizedBox(height: 12),
        Container(
          width: 240, height: 100,
          padding: const EdgeInsets.only(left: 10, top: 8, right: 20, bottom: 12),
          color: const Color(0x80336699),
          child: const Align(alignment: Alignment.topLeft,
            child: Text('Nested text', style: TextStyle(fontFamily: 'Arial', fontSize: 14, height: 1.5, color: Colors.black))),
        ),
        const SizedBox(height: 12),
        const SizedBox(width: 240, height: 40, child: ColoredBox(color: Color(0xFF224466))),
      ],
    ),
  );
}
