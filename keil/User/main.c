#include "stm32f10x.h"                  // Device header
#include "Delay.h"
#include "Serial.h"
#include "AD.h"
#include "stdio.h"
#include "Stepper.h"
#include "Key.h"
#include "dht11.h"
#include "Timer.h"
#include  "OLED.h"
#include "PWM.h"

/******************************************************/
//变量定义

uint8_t Serial_Flag;
uint8_t RxData;//串口接收数据
uint16_t ms_Tick;//毫秒计数

uint16_t s_Tick;//每秒计数

u8 Temperature1,Moist1;//温度 湿度 
u8 Temperature2,Moist2;//温度 湿度 


uint16_t CO2;


uint8_t Inter_Face;//界面
uint16_t PWM_Num = 50;//PWM值
uint16_t Light;	//定义AD值变量 
uint8_t Person_Flag;//是否有人标志


uint16_t Temperature_Min = 20;	 //温度下限
uint16_t Temperature_Max = 40; //温度上限

uint16_t Light_Min = 20;	 //光照下限
uint16_t Light_Max = 80;	 //光照上限

uint16_t Moist_Min = 30;	 //湿度下限
uint16_t Moist_Max = 80;	 //湿度上限

uint16_t Moist2_Min = 30;	 //土壤湿度下限

uint16_t CO2_Max = 80;	 //CO2上限

uint8_t KeyNum;		//定义用于接收按键键码的变量

uint8_t Angle = 100;//舵机角度
uint8_t Flag;//

char String1[16];				
char String2[16];		
char String3[16];	
char String4[16];

char Uart_String1[160];					//定义字符数组（JSON输出缓冲区）
char Uart_String2[30];					//定义字符数组
char Uart_String3[30];					//定义字符数组
char Uart_String4[30];					//定义字符数组


/******************************************************/
//函数定义
void Serial_Proc(void);//串口函数声明
void Text_Proc(void);
void Key_Proc(void);

int main(void)
{
	RCC_SYSCLKConfig(RCC_SYSCLKSource_HSI);//串口内部时钟配置，必须放在最开始
	/*模块初始化*/
	
	Key_Init();		//按键初始化                                             
	Serial_Init();						//串口初始化
	Timer_Init();		//定时中断初始化
	AD_Init();				//AD初始化
	OLED_Init();				//OLED初始化
	PWM_Init();		//PWM初始化
//	Servo_PWM_Init();//舵机初始化
	/////////////////////////////
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA|RCC_APB2Periph_GPIOB, ENABLE);	//开启GPIOA B的时钟
															
	GPIO_InitTypeDef GPIO_InitStructure;					//定义结构体变量
	
	GPIO_InitStructure.GPIO_Mode = GPIO_Mode_Out_PP;		//GPIO模式，赋值为推挽输出模式
	GPIO_InitStructure.GPIO_Pin =  GPIO_Pin_2  ;				//GPIO引脚，赋值为所有引脚
	GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;		//GPIO速度，赋值为50MHz
	
	GPIO_Init(GPIOB, &GPIO_InitStructure);
	
	GPIO_InitStructure.GPIO_Mode = GPIO_Mode_Out_PP;		//GPIO模式，赋值为推挽输出模式
	GPIO_InitStructure.GPIO_Pin = GPIO_Pin_6 | GPIO_Pin_7 
	 |GPIO_Pin_12 | GPIO_Pin_13 | GPIO_Pin_14 | GPIO_Pin_15 ;				//GPIO引脚，赋值为所有引脚
	GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;		//GPIO速度，赋值为50MHz
	
	GPIO_Init(GPIOA, &GPIO_InitStructure);	
	/////////////////////////////
	
	while (1)
	{
		Key_Proc();
		Text_Proc();
		Serial_Proc();
	}
}
void Text_Proc(void)
{

		/*参数测量*/
		if(Flag == 1)
		{
			
			Flag = 0;
	
			TIM_Cmd(TIM3, DISABLE);			//能TIM2，定时器开始运行

			DHT11_Read_Data(GPIOB, GPIO_Pin_14, &Temperature1, &Moist1);
			DHT11_Read_Data(GPIOB, GPIO_Pin_15, &Temperature2, &Moist2);

			TIM_Cmd(TIM3, ENABLE);			//使能TIM2，定时器开始运行
		}
		
		Light = AD_GetValue(ADC_Channel_2)/40.96;		//光照检测
//		Moist2 = AD_GetValue(ADC_Channel_3)/40.96;		//土壤湿度检测
		CO2 = AD_GetValue(ADC_Channel_4)/40.96;		//CO2检测
		//LCD1602内容打印
		if(Inter_Face == 0)
		{
			sprintf(String1,"Tem:%dC       ",(unsigned int)Temperature1);//
			sprintf(String2,"Max:%d Min:%d ",Temperature_Max,Temperature_Min);//
			sprintf(String3,"Moi:%d%% Min:%d ",(unsigned int)Moist1,Moist_Min);//
			sprintf(String4,"Lig:%d%% Min:%d ",(unsigned int)Light,Light_Min);//

		}
		else if(Inter_Face == 1)
		{
			
			sprintf(String1,"S-M:%d%% Min:%d ",(unsigned int)Moist2,Moist2_Min);
			sprintf(String2,"CO2:%d Max:%d ",CO2,CO2_Max);//
			sprintf(String3,"              ");//
			sprintf(String4,"              ");//

		}
//		

		
		
		
		
		
		
		PWM_SetCompare1(PWM_Num);//设置灯光亮度
		
		OLED_ShowString(1, 1, (char *)String1);//第一行显示内容
		OLED_ShowString(2, 1, (char *)String2);//第二行显示内容
		OLED_ShowString(3, 1, (char *)String3);//第三行显示内容
		OLED_ShowString(4, 1, (char *)String4);//第四行显示内容
	
	
		//串口内容打印（JSON单行，便于上位机按行解析）
		sprintf(Uart_String1,
				"{\"SoilMoisture\":%u,\"CurrentHumidity\":%u,\"CurrentTemperature\":%u,\"co2\":%u,\"LightLux\":%u}\r\n",
				(unsigned int)Moist2,
				(unsigned int)Moist1,
				(unsigned int)Temperature1,
				(unsigned int)CO2,
				(unsigned int)Light);
		
		
		
		//超出阈值报警
		if((Temperature1 < Temperature_Min)||(Temperature1 > Temperature_Max)||(Moist1 < Moist_Min)||(Light < Light_Min)||(Moist2 < Moist2_Min)||(CO2 > CO2_Max))
		{
			GPIO_SetBits(GPIOA,GPIO_Pin_15);
		}
		else GPIO_ResetBits(GPIOA,GPIO_Pin_15);
		//超出阈值开制冷
		if(Temperature1 < Temperature_Min)
		{
			GPIO_SetBits(GPIOA,GPIO_Pin_13);
		}
		else GPIO_ResetBits(GPIOA,GPIO_Pin_13);
		
		//超出阈值开制冷
		if(Temperature1 > Temperature_Max)
		{
			GPIO_SetBits(GPIOA,GPIO_Pin_12);
		}
		else GPIO_ResetBits(GPIOA,GPIO_Pin_12);
		//超出阈值开水泵
		if(Moist2 < Moist2_Min)
		{
			GPIO_SetBits(GPIOA,GPIO_Pin_6);
		}
		else GPIO_ResetBits(GPIOA,GPIO_Pin_6);
		
		//超出阈值开水泵
		if(Moist1 < Moist_Min)
		{
			GPIO_SetBits(GPIOA,GPIO_Pin_7);
		}
		else GPIO_ResetBits(GPIOA,GPIO_Pin_7);
		
		
		//光照超出阈值开关
		if(Light < Light_Min)
		{
			Angle = 180;
			PWM_Num = 100;
		}
		else 
		{
			PWM_Num = 0;
			Angle = 0;
		}
		
		
		//超出阈值开风扇
		if(CO2 > CO2_Max)
		{
			GPIO_SetBits(GPIOA,GPIO_Pin_14);
		}
		else GPIO_ResetBits(GPIOA,GPIO_Pin_14);

		Servo_SetAngle(Angle,2);
}

void Key_Proc(void)
{
		KeyNum = Key_GetNum();		//获取按键键码
		
		if (KeyNum == 1)			//按键1按下
		{
			if(++Inter_Face == 2)Inter_Face = 0;//界面切换
			
		}
		

	

}
void Serial_Proc(void)
{
		if(Serial_GetRxFlag() == 1)			//检查串口接收数据的标志位
		{
			RxData = Serial_GetRxData();		//获取串口接收的数据
			
			if(RxData == '1')
			{
				Temperature_Max++;
				Serial_SendString("Temperature_Max+1 !\r\n");
				
			}
			else if(RxData == '2')
			{
				Temperature_Max--;
				Serial_SendString("Temperature_Max-1 !\r\n");
				
			}
			
}
}
	
/**
  * 函    数：TIM3中断函数
  * 参    数：无
  * 返 回 值：无
  * 注意事项：此函数为中断函数，无需调用，中断触发后自动执行
  *           函数名为预留的指定名称，可以从启动文件复制
  *           请确保函数名正确，不能有任何差异，否则中断函数将不能进入
  */
void TIM3_IRQHandler(void)
{
	if (TIM_GetITStatus(TIM3, TIM_IT_Update) == SET)		//判断是否是TIM2的更新事件触发的中断
	{
		
		ms_Tick++;
		
		if((ms_Tick % 100) == 0)//每1s发送一次数据
		{
			Flag = 1;
			s_Tick++;
			Serial_SendString(Uart_String1);			//串口发送字符数组（字符串）
		}
		
	
		TIM_ClearITPendingBit(TIM3, TIM_IT_Update);			//清除TIM2更新事件的中断标志位
															//中断标志位必须清除
															//否则中断将连续不断地触发，导致主程序卡死
		
	}
}

